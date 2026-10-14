"""Reverse-proxy trust checks and client IP resolution."""
from __future__ import annotations

import ipaddress
import logging
from typing import Any

from fastapi import Request

from backend import config

log = logging.getLogger("typst.main")


def _fwd_entries(allow: str) -> list[str]:
    # C10: one normalizer for FORWARDED_ALLOW_IPS entries, shared by the
    # runtime trust check and the startup gate (they must agree on what is
    # "open"): split on comma/space, drop empties, strip whitespace and
    # [brackets] (IPv6 is written both ways).
    return [e for raw in (allow or "").replace(",", " ").split() if (e := raw.strip().strip("[]"))]


def _proxy_peer_allowed(peer: str, allow: str) -> bool:
    # C10: is the TCP peer (req.client.host, already de-spoofed by uvicorn's
    # --forwarded-allow-ips at the edge) inside FORWARDED_ALLOW_IPS?
    # Entries are IPs or CIDRs, comma/space separated. "*" matches (startup
    # refuses it together with TRUST_PROXY=true); invalid entries are
    # ignored fail-closed (never widen trust).
    try:
        ip = ipaddress.ip_address((peer or "").strip())
    except ValueError:
        return False
    for e in _fwd_entries(allow):
        if e == "*":
            return True
        try:
            if "/" in e:
                if ip in ipaddress.ip_network(e, strict=False):
                    return True
            elif ip == ipaddress.ip_address(e):
                return True
        except ValueError:
            log.warning("FORWARDED_ALLOW_IPS ignoring invalid entry %r", e)
    return False


def _proxy_trusted(req: Request) -> bool:
    # C10: single gate for every X-Forwarded-* use. TRUST_PROXY=true alone is
    # not enough: it would let any direct client spoof X-Forwarded-For
    # (rotate rate-limit buckets at will) and X-Forwarded-Proto (force the
    # Secure cookie flag / HSTS). Headers count only from allowlisted peers.
    try:
        cfg = config.load()
    except Exception:
        return False
    if not cfg.TRUST_PROXY:
        return False
    try:
        peer = req.client.host if req.client else ""
    except Exception:
        peer = ""
    return _proxy_peer_allowed(peer or "", cfg.FORWARDED_ALLOW_IPS)


def _proxy_startup_check(cfg: Any) -> None:
    # C10: refuse to start with TRUST_PROXY=true and an effectively-open
    # allowlist (README: never '*' — any client could spoof IP/proto and the
    # rate limiter would key on attacker-chosen buckets). Empty allowlist is
    # only a warning: it fails closed (headers ignored, same as TRUST_PROXY=false).
    if not cfg.TRUST_PROXY:
        return
    allow = str(cfg.FORWARDED_ALLOW_IPS or "")
    if not allow.strip():
        log.warning("TRUST_PROXY=true but FORWARDED_ALLOW_IPS is empty: proxy headers ignored")
        return
    for e in _fwd_entries(allow):
        if e == "*" or e in ("0.0.0.0/0", "::/0"):
            log.error("refusing to start: TRUST_PROXY=true with open FORWARDED_ALLOW_IPS=%r "
                      "(any client could spoof IP/proto); restrict it to the proxy", e)
            raise SystemExit(1)


def client_ip(req: Request) -> str:
    try:
        if _proxy_trusted(req):
            fwd = req.headers.get("x-forwarded-for", "")
            if len(fwd) > 1000:
                log.warning("suspicious X-Forwarded-For length (%d)", len(fwd))
            if fwd.strip():
                return fwd.split(",")[0].strip()[:45] or "?"
    except Exception:
        pass
    return req.client.host if req.client else "?"
