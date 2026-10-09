"""Shared request helpers: auth dependency, access checks, quota, file locations."""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

from fastapi import Cookie, HTTPException, Request, status

from backend import auth, config, db, ratelimit
from backend.constants import FOLDER_MAX, RATE_DEFAULTS
from backend.services import quota as quota_svc
from backend.services.proxy import client_ip

log = logging.getLogger("typst.main")

COOKIE = auth.COOKIE


ROOT = Path(__file__).resolve().parent.parent

try:
    FILES_DIR = config.load().DATA_DIR / "files"
except Exception as e:
    log.warning("config DATA_DIR missing, fallback data/files: %s", e)
    FILES_DIR = ROOT / "data" / "files"


# Startup default (backwards compat: tests monkeypatch main.FILES_DIR);
# get_files_dir() below is the live view.
_FILES_DIR_STARTUP = FILES_DIR


def get_files_dir() -> Path:
    """Live files location: current DATA_DIR unless FILES_DIR was overridden.

    Honors an explicit FILES_DIR reassignment (tests isolate via
    monkeypatch.setattr(main, "FILES_DIR", tmp)); otherwise follows
    config.load().DATA_DIR so a later DATA_DIR change stays consistent
    with db.get_db_path().
    """
    try:
        live = config.load().DATA_DIR / "files"
    except Exception:
        return FILES_DIR
    try:
        if FILES_DIR != _FILES_DIR_STARTUP:
            return FILES_DIR
    except Exception:
        return FILES_DIR
    return live


ALLOWED_IMG = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".pdf", ".typ", ".bib", ".csv"}

TEXT_SUFFIX = {".typ", ".bib", ".csv"}


# B15: long-cached shell assets. Immutable only where the URL carries a
# ?v= cache-buster (vendor-cm.js?v=4, manifest.json?v=2, icons, icon.svg?v=3);
# keep ?v in sync on redeploy or a stale bundle lingers in HTTP cache
# (content-hashed filenames = proper fix).
# sw.js is gone (worker dropped 2026-10-03): .js stays no-store for future scripts.
IMMUTABLE_SHELL = frozenset({"vendor-cm.js", "manifest.json", "icon-192.png", "icon-512.png", "icon.svg"})


def me(session: str | None = Cookie(default=None, alias=COOKIE)) -> str:
    user = auth.verify_session(session or "")
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return user


def need_access(user: str, doc_id: str, allow_trashed: bool = False) -> str:
    r = db.doc_role(user, doc_id)
    if not r:
        raise HTTPException(404, "Document not found")
    if not allow_trashed and db.is_trashed(doc_id):
        raise HTTPException(410, "In trash - restore first")
    return r


def limited(req: Request, scope: str, key: str = "") -> None:
    # Limits always come from Config (live); RATE_DEFAULTS only documents fallbacks.
    s = scope.lower()
    try:
        cfg = config.load()
        if s == "register":
            lim, win = int(cfg.RATE_REGISTER_PER_HOUR), 3600
        else:
            lim, win = int(getattr(cfg, f"RATE_{s.upper()}_PER_MIN", RATE_DEFAULTS.get(s, (30, 60))[0])), 60
    except Exception:
        lim, win = RATE_DEFAULTS.get(s, (30, 60))
    if not ratelimit.allow(f"{scope}:{client_ip(req)}", lim, win):
        log.warning("rate-limit %s (ip-bucket)", scope)
        raise HTTPException(429, "Too many requests - try again shortly")
    if key and not ratelimit.allow(f"{scope}:user:{key}", lim, win):
        log.warning("rate-limit %s (user-bucket)", scope)
        raise HTTPException(429, "Too many requests - try again shortly")


def busy_503(what: str, e: Exception) -> HTTPException:
    log.warning("%s busy: %s", what, e)
    return HTTPException(503, "Database busy, try again")


def user_bytes(user: str) -> int:
    # Backwards-compat wrapper (tests use main.user_bytes); logic lives in
    # backend.services.quota so sync can use it without importing main.
    return quota_svc.user_bytes(user)


def check_quota(user: str, extra: int) -> None:
    return quota_svc.check_quota(user, extra)


def _owner(doc_id: str, fallback: str) -> str:
    return quota_svc.doc_owner(doc_id, fallback)


def need_edit(user: str, doc_id: str) -> str:
    # Returns the role like need_access (consistent); callers need the check only.
    # need_access already rejects trashed docs (410), no re-check here.
    role = need_access(user, doc_id)
    if role not in ("owner", "editor"):
        raise HTTPException(403, "Reviewer can only comment")
    return role


def _tx_role(con: sqlite3.Connection, user: str, doc_id: str) -> str:
    # B5: authoritative role re-check ON the tx connection. need_access /
    # need_edit open their own connection, so a pre-tx check can go stale
    # between the check and BEGIN IMMEDIATE (owner unshares/downgrades in
    # the gap). Call this as the first statement of every mutating db.tx()
    # block; the outer check stays as a cheap fast-path only. Same
    # fail-closed codes as need_access (404 hides existence, 410 trash).
    d = con.execute("SELECT owner, trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
    if not d:
        raise HTTPException(404, "Document not found")
    if d["trashed"]:
        raise HTTPException(410, "In trash - restore first")
    if d["owner"] == user:
        return "owner"
    s = con.execute("SELECT role FROM shares WHERE doc_id=? AND username=?",
                    (doc_id, user)).fetchone()
    if not s:
        raise HTTPException(404, "Document not found")
    return s["role"]


def _folder_counts(con: sqlite3.Connection, owner: str, kind: str) -> list[dict]:
    # Shared by list_folders (docs) / list_tpl_folders (templates): counted
    # names from the items table merged with explicitly created (maybe empty)
    # folders from the folders table.
    if kind == "doc":
        table, extra = "docs", "AND trashed=0"
    else:
        table, extra = "templates", ""
    rows = con.execute(f"SELECT folder, COUNT(*) AS n FROM {table} WHERE owner=? AND folder<>'' {extra} "
                       "GROUP BY folder ORDER BY folder", (owner,)).fetchall()
    counts = {r["folder"]: r["n"] for r in rows}
    for r in con.execute("SELECT name FROM folders WHERE owner=? AND kind=? ORDER BY name",
                         (owner, kind)).fetchall():
        counts.setdefault(r["name"], 0)
    return [{"folder": f, "n": counts[f]} for f in sorted(counts)]


def ensure_folder(con, user: str, kind: str, name: str) -> None:
    n = name.strip()[:FOLDER_MAX]
    if n:
        con.execute("INSERT OR IGNORE INTO folders (owner, kind, name, created_at) VALUES (?,?,?,?)",
                    (user, kind, n, db.now_iso()))


def check_folder_name(name: str) -> str:
    n0 = name.strip()
    if len(n0) > FOLDER_MAX:
        raise HTTPException(400, "Folder name too long")
    n = n0[:FOLDER_MAX]
    if not n:
        raise HTTPException(400, "Empty folder name")
    return n


DOC_ID_RE = re.compile(r"^d_[A-Za-z0-9_-]+$")


def check_doc_id(doc_id: str) -> None:
    if not DOC_ID_RE.fullmatch(doc_id or ""):
        raise HTTPException(404, "Document not found")
