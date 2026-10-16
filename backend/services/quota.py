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


def user_bytes(user: str, con: sqlite3.Connection | None = None) -> int:
    # File sizes come from the files table (1D), never from a filesystem
    # walk. Write-through on every mutation keeps it exact; list_files()
    # reconciles external writers (duplicate, MCP text edit) on next read.
    # Signatures stay put: sync.py reads quota through these (short-lived
    # cache there, Interna here).
    from backend import db as _db

    owns_connection = con is None
    con = con if con is not None else _db.connect()
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
        pr = con.execute(
            "SELECT COALESCE(SUM(LENGTH(CAST(r.content AS BLOB))),0) AS n "
            "FROM project_resources r JOIN projects p ON p.id=r.project_id WHERE p.owner=?", (user,)
        ).fetchone()
        total += int(pr["n"] or 0)
        ps = con.execute("SELECT COALESCE(SUM(LENGTH(CAST(s.content AS BLOB))),0) AS n FROM project_snapshots s JOIN projects p ON p.id=s.project_id WHERE p.owner=?", (user,)).fetchone()
        total += int(ps["n"] or 0)
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
        if owns_connection:
            con.close()
    return total


def is_over_quota(user: str) -> bool:
    """True when the user is over quota. Lets OperationalError through."""
    return user_bytes(user) > user_cap(user)


def migration_allowance(user: str, con: sqlite3.Connection | None = None) -> int:
    from backend import db

    own = con is None
    con = db.connect() if con is None else con
    try:
        row = con.execute("SELECT migration_bytes FROM users WHERE name=?", (user,)).fetchone()
        return int(row[0]) if row else 0
    finally:
        if own:
            con.close()


def user_cap(user: str, con: sqlite3.Connection | None = None) -> int:
    return quota_cap() + migration_allowance(user, con)


def doc_owner(doc_id: str, fallback: str = "") -> str:
    from backend import db as _db

    con = _db.connect()
    try:
        r = con.execute("SELECT owner FROM docs WHERE id=?", (doc_id,)).fetchone()
        return r["owner"] if r else fallback
    finally:
        con.close()


def check_quota(user: str, extra: int, con: sqlite3.Connection | None = None) -> None:
    current = user_bytes(user) if con is None else user_bytes(user, con)
    if current + extra > user_cap(user, con):
        raise HTTPException(413, "Quota exceeded")


def invalidate_quota_cache(owner: str) -> None:
    """Drop sync's short-lived quota verdict after a quota-relevant write.

    sync.py (track 1C) owns the cache and the real invalidate function;
    this wrapper lazy-resolves it so callers stay cycle-free and keep
    working standalone (no-op until the 1C side is merged). Never raises.
    """
    try:
        from backend import sync as _sync

        inv = getattr(_sync, "invalidate_quota_cache", None)
        if inv is not None:
            inv(owner)
    except Exception as e:
        log.warning("invalidate_quota_cache failed for %s: %s", owner, e)


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
    if user_bytes(owner) + extra > user_cap(owner):
        raise HTTPException(413, "Quota exceeded")
    yield
    try:
        over = user_bytes(owner) > user_cap(owner)
    except sqlite3.OperationalError:
        raise
    if over:
        if rollback is not None:
            try:
                rollback()
            except Exception as e:
                log.warning("quota_guard rollback failed: %s", e)
        raise HTTPException(413, "Quota exceeded")
