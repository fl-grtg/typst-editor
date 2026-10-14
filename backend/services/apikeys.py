"""API key creation, verification and role capping."""
from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, datetime

from fastapi import Cookie, HTTPException, Request, status

from backend import auth, db, deps

log = logging.getLogger("typst.main")


# --- API keys (MCP/agent access, M1) ---
KEY_RE = re.compile(r"^tpe_[0-9a-f]{8}_[0-9a-f]{32}$")

KEY_ROLES = ("editor", "reviewer")

_ROLE_RANK = {"reviewer": 1, "editor": 2, "owner": 3}


def cap_min(cap: str, role: str) -> str:
    # Effective rights = minimum of key sort and doc_role(); session cap
    # "owner" never restricts. Admin stays human UI: keys max out at editor.
    if cap == "owner":
        return role
    return role if _ROLE_RANK.get(role, 0) < _ROLE_RANK.get(cap, 0) else cap


def mint_api_key() -> tuple[str, str, str]:
    prefix = secrets.token_hex(4)
    secret = secrets.token_hex(16)
    return db.new_id("k_"), f"tpe_{prefix}_{secret}", prefix


def verify_api_key(key: str) -> dict | None:
    if not key or not KEY_RE.fullmatch(key):
        return None
    con = db.connect()
    try:
        r = con.execute("SELECT id, username, name, role, expires_at, revoked FROM api_keys WHERE key_hash=?",
                        (auth.sha(key),)).fetchone()
        if not r or r["revoked"]:
            return None
        if r["role"] not in KEY_ROLES:
            return None
        if r["expires_at"]:
            try:
                exp = datetime.fromisoformat(r["expires_at"])
            except (ValueError, TypeError):
                return None  # corrupt expiry: fail closed
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if exp <= datetime.now(UTC):
                return None
        try:
            con.execute("UPDATE api_keys SET last_used=? WHERE id=?", (db.now_iso(), r["id"]))
            con.commit()
        except Exception as e:
            log.warning("api key last_used failed: %s", e)
        return {"id": r["id"], "user": r["username"], "role": r["role"], "key_name": r["name"] or ""}
    finally:
        con.close()


def me_with_key(req: Request, session: str | None = Cookie(default=None, alias=deps.COOKIE)) -> tuple[str, str]:
    # Bearer first (MCP/agents), then cookie fallback (human UI).
    # Returns (user, cap): cap "owner" for sessions, else the key role.
    authz = req.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        hit = verify_api_key(authz[7:].strip())
        if not hit:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
        return hit["user"], hit["role"]
    user = auth.verify_session(session or "")
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return user, "owner"
