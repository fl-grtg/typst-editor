"""Named in-process locks and the single-instance file lock."""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any

from backend import db
from backend.constants import LOCK_NAME

log = logging.getLogger("typst.main")


_LOCK_FH = None

_DOC_LOCKS: dict[str, threading.Lock] = {}

_DOC_LOCKS_GUARD = threading.Lock()

_EXPORT_LOCKS: dict[str, threading.Lock] = {}


def _lock_for(store: dict[str, threading.Lock], key: str) -> threading.Lock:
    with _DOC_LOCKS_GUARD:
        lock = store.get(key)
        if lock is None:
            lock = threading.Lock()
            store[key] = lock
        return lock


def _named_lock(key: str) -> threading.Lock:
    # B7 (renamed from _doc_lock): a generic named-lock registry, NOT only
    # for docs — keys are heterogeneous ("register", "dup:{user}",
    # "upload:{doc_id}"). Keys are case-sensitive dict keys: "dup:Alice"
    # and "dup:alice" are different locks (see tests/test_locks.py).
    return _lock_for(_DOC_LOCKS, key)


def _export_lock(user: str) -> threading.Lock:
    return _lock_for(_EXPORT_LOCKS, user)


def _drop_doc_locks(doc_id: str) -> None:
    # Drop per-doc locks when the room is gone (no reaper thread).
    # Never drop a held lock: the holder still relies on it for mutual exclusion.
    with _DOC_LOCKS_GUARD:
        for _key in (f"upload:{doc_id}", f"ws:{doc_id}"):
            _lock = _DOC_LOCKS.get(_key)
            if _lock is not None and not _lock.locked():
                _DOC_LOCKS.pop(_key, None)


def _drop_user_locks(user: str) -> None:
    # Drop per-user locks when the user is gone (no reaper thread).
    with _DOC_LOCKS_GUARD:
        _DOC_LOCKS.pop(f"dup:{user}", None)
        _EXPORT_LOCKS.pop(user, None)


def _lock_path() -> Path:
    return Path(str(db.get_db_path())).parent / LOCK_NAME


def _filelock(fh: Any, lock: bool) -> None:
    # One helper for the fcntl/msvcrt split (used by acquire + release).
    _fcntl: Any = None
    _msvcrt: Any = None
    if sys.platform != "win32":
        try:
            import fcntl as _f

            _fcntl = _f
        except ImportError as e:
            log.warning("fcntl unavailable, try msvcrt: %s", e)
    try:
        import msvcrt as _m

        _msvcrt = _m
    except ImportError as e:
        log.debug("msvcrt unavailable (expected on linux): %s", e)
    if _fcntl is not None:
        _fcntl.flock(fh.fileno(), (_fcntl.LOCK_EX | _fcntl.LOCK_NB) if lock else _fcntl.LOCK_UN)
    elif _msvcrt is not None:
        fh.seek(0)
        _msvcrt.locking(fh.fileno(), _msvcrt.LK_NBLCK if lock else _msvcrt.LK_UNLCK, 1)
    else:
        raise OSError("no file lock available")


def _acquire_single_lock() -> None:
    global _LOCK_FH
    if _LOCK_FH is not None:
        return
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    try:
        fh.seek(0, 2)
        if fh.tell() == 0:
            fh.write(b"\0")
            fh.flush()
        _filelock(fh, True)
        _LOCK_FH = fh
    except Exception as e:
        try:
            fh.close()
        except Exception as ce:
            log.warning("single-lock close after acquire fail: %s", ce)
        log.error("another instance is already running, exit: %s", e)
        raise SystemExit(1) from None


def _release_single_lock() -> None:
    global _LOCK_FH
    fh, _LOCK_FH = _LOCK_FH, None
    if fh is None:
        return
    try:
        try:
            _filelock(fh, False)
        except Exception as e:
            log.warning("single-lock unlock failed: %s", e)
        fh.close()
    except Exception as e:
        log.warning("single-lock release failed: %s", e)
