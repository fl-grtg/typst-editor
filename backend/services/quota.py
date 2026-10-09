"""Quota accounting: single source for main + sync (no import cycle).

user_bytes/check_quota lived in backend.main, which sync could only reach
via a lazy ``from backend import deps`` import. This module owns the logic;
main keeps thin wrappers for backwards compat (tests use main.user_bytes).
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

log = logging.getLogger(__name__)


def files_dir() -> Path:
    # Live view via deps.get_files_dir() (itself follows DATA_DIR unless
    # FILES_DIR was explicitly reassigned); fall back to the patched
    # deps.FILES_DIR attr directly so tmp isolation keeps working even if
    # the accessor is unavailable, then to config, then to a static default.
    try:
        from backend import deps as _deps

        get = getattr(_deps, "get_files_dir", None)
        if callable(get):
            try:
                return get()
            except Exception:
                pass
        p = getattr(_deps, "FILES_DIR", None)
        if isinstance(p, Path):
            return p
        if p:
            return Path(str(p))
    except Exception:
        pass
    try:
        from backend import config as _cfg

        return _cfg.load().DATA_DIR / "files"
    except Exception:
        return Path(__file__).resolve().parent.parent.parent / "data" / "files"


def quota_cap() -> int:
    try:
        from backend import config as _cfg

        return int(_cfg.load().MAX_BYTES_PER_USER)
    except Exception:
        return 524288000


def user_bytes(user: str) -> int:
    # File sizes come from the files table (1D), never from a filesystem
    # walk. Write-through on every mutation keeps it exact; list_files()
    # reconciles external writers (duplicate, MCP text edit) on next read.
    # Signatures stay put: sync.py reads quota through these (short-lived
    # cache there, Interna here).
    from backend import db as _db

    con = _db.connect()
    try:
        r = con.execute(
            "SELECT COALESCE(SUM(LENGTH(CAST(content AS BLOB))),0)"
            " + COALESCE(SUM(LENGTH(yjs)),0) AS n FROM docs WHERE owner=?",
            (user,),
        ).fetchone()
        total = int(r["n"] or 0)
        s = con.execute(
            "SELECT COALESCE(SUM(LENGTH(CAST(s.content AS BLOB))),0) AS n"
            " FROM snapshots s JOIN docs d ON d.id=s.doc_id WHERE d.owner=?",
            (user,),
        ).fetchone()
        total += int(s["n"] or 0)
        t = con.execute(
            "SELECT COALESCE(SUM(LENGTH(CAST(content AS BLOB))),0) AS n"
            " FROM templates WHERE owner=?",
            (user,),
        ).fetchone()
        total += int(t["n"] or 0)
        a = con.execute("SELECT avatar FROM users WHERE name=?", (user,)).fetchone()
        if a and a["avatar"]:
            total += len(a["avatar"].encode("utf-8"))
        f = con.execute(
            "SELECT COALESCE(SUM(fl.size),0) AS n FROM files fl "
            "JOIN docs d ON d.id=fl.doc_id WHERE d.owner=?",
            (user,),
        ).fetchone()
        total += int(f["n"] or 0)
    finally:
        con.close()
    return total


def is_over_quota(user: str) -> bool:
    """True when the user is over quota. Lets OperationalError through."""
    return user_bytes(user) > quota_cap()


def doc_owner(doc_id: str, fallback: str = "") -> str:
    from backend import db as _db

    con = _db.connect()
    try:
        r = con.execute("SELECT owner FROM docs WHERE id=?", (doc_id,)).fetchone()
        return r["owner"] if r else fallback
    finally:
        con.close()


def check_quota(user: str, extra: int) -> None:
    if user_bytes(user) + extra > quota_cap():
        raise HTTPException(413, "Quota exceeded")


@contextmanager
def quota_guard(
    owner: str,
    extra: int = 0,
    rollback: Callable[[], None] | None = None,
) -> Iterator[None]:
    """Pre-check (bytes + extra) then post-check with optional rollback.

    Use around a write: pre-check fails fast before work, post-check catches
    races (second walk) and calls rollback() before raising 413.
    OperationalError passes through so callers map it to 503.
    """
    if user_bytes(owner) + extra > quota_cap():
        raise HTTPException(413, "Quota exceeded")
    yield
    try:
        over = user_bytes(owner) > quota_cap()
    except sqlite3.OperationalError:
        raise
    if over:
        if rollback is not None:
            try:
                rollback()
            except Exception as e:
                log.warning("quota_guard rollback failed: %s", e)
        raise HTTPException(413, "Quota exceeded")
