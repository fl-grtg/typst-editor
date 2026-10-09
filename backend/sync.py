"""Yjs-compatible sync server in Python (pycrdt).

Write-behind persistence (1C):
  WS updates only mark rooms dirty; a background flusher persists dirty rooms
  every WRITE_BEHIND_FLUSH_SECONDS and on last disconnect. A `kill -9` loses
  at most WRITE_BEHIND_FLUSH_SECONDS of edits (see the constant below).

No synchronous DB access runs on the event loop in the WS hot path (1C):
  initial checks, room load, role/session/trash rechecks and the final save
  all go through `asyncio.to_thread`. Role, trash status and session live in
  room state and are invalidated on share/unshare/delete/logout.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from urllib.parse import urlparse

from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect
from pycrdt import Doc, Text

from backend import auth, db
from backend.constants import AWARE_MAX, CACHE_TTL, MAX_TXT, ROOMS_MAX, SESSION_RECHECK_TTL
from backend.services import quota as _quota

log = logging.getLogger("typst.sync")

COOKIE = auth.COOKIE

MSG_SYNC = 0
MSG_AWARENESS = 1
STEP1 = 0
STEP2 = 1
UPDATE = 2

# 1C: max loss window on a hard crash. Flush every 2s + on last disconnect.
# Track 1D note: this is the documented kill -9 loss bound.
WRITE_BEHIND_FLUSH_SECONDS = 2.0
# 1C: short-lived quota cache in sync.py ONLY (quota internals stay in
# services/quota.py, owned by 1D). Keyed by owner -> (is_over, monotonic_ts).
QUOTA_CACHE_TTL = 10.0
# Trash-status cache per room (invalidated on drop/kick/delete).
# TTL is 0 (revalidate on every WS message via to_thread): trash/delete must
# kick immediately, and the pre-1C code checked fresh each message. The room
# still holds the last value (r["trashed"]) so flush/drop paths share state,
# but message guards never serve stale.
TRASH_CACHE_TTL = 0.0

rooms: dict[str, dict] = {}
_sess_cache: dict[str, tuple[str | None, float]] = {}
_quota_cache: dict[str, tuple[bool, float]] = {}
_flush_task: asyncio.Task | None = None


def read_var(data: bytes, pos: int) -> tuple[int, int]:
    n = s = 0
    while True:
        if pos >= len(data):
            raise ValueError("short")
        b = data[pos]
        pos += 1
        n |= (b & 0x7F) << s
        s += 7
        if not b & 0x80:
            return n, pos


def write_var(n: int) -> bytes:
    out = bytearray()
    while n > 127:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    out.append(n)
    return bytes(out)


def blob(*parts: bytes) -> bytes:
    return b"".join(parts)


def room(doc_id: str) -> dict:
    r = rooms.get(doc_id)
    if r is None:
        if len(rooms) >= ROOMS_MAX:
            # Soft cap: only evict idle rooms, never drop active ones.
            idle = [k for k, v in rooms.items() if not v.get("conns")]
            if idle:
                victim = min(idle, key=lambda k: rooms[k].get("saved", 0.0))
                vr = rooms.get(victim)
                if vr is not None and vr.get("dirty") and fresh_trashed_ok(victim):
                    try:
                        db.save_room(victim, vr["doc"].get_update(), str(vr["doc"].get("typst", type=Text)))
                    except Exception as e:
                        log.warning("room %s: evict save failed, keep dirty: %s", victim, e)
                        vr["dirty"] = True
                    else:
                        rooms.pop(victim, None)
                        _drop_locks(victim)
                else:
                    rooms.pop(victim, None)
                    _drop_locks(victim)
            # else over cap: still create new room, cap is soft
        doc: Doc = Doc()
        yjs, content = db.get_room_state(doc_id)
        init_dirty = False
        if yjs:
            try:
                doc.apply_update(yjs)
            except Exception as e:
                log.warning("room %s: corrupt yjs, rebuild from content: %s", doc_id, e)
                doc = Doc()  # fresh: never append content onto half-applied state
                if content:
                    with doc.transaction():
                        fresh = doc.get("typst", type=Text)
                        fresh += content
                    init_dirty = True
                    if fresh_trashed_ok(doc_id):
                        try:
                            db.save_room(doc_id, doc.get_update(), content)
                        except Exception as e:
                            log.warning("room %s: save after rebuild failed: %s", doc_id, e)
            # yjs applied cleanly: authoritative, do NOT append content (save_room writes both together)
        elif content:
            with doc.transaction():
                text = doc.get("typst", type=Text)
                text += content
            if fresh_trashed_ok(doc_id):
                try:
                    db.save_room(doc_id, doc.get_update(), content)
                except Exception as e:
                    log.warning("room %s: save after rebuild failed: %s", doc_id, e)
                    init_dirty = True
            # trashed: skip persist into trashed doc
        try:
            trashed_now = db.is_trashed(doc_id)
        except Exception as e:
            log.warning("room %s: trashed check failed, assume open: %s", doc_id, e)
            trashed_now = False
        try:
            text_len = len(str(doc.get("typst", type=Text)))
        except Exception as e:
            log.warning("room %s: text_len failed: %s", doc_id, e)
            text_len = len(content or "")
        r = {"doc": doc, "conns": set(), "users": {}, "tokens": {}, "sess_at": {},
             "saved": time.monotonic(), "dirty": init_dirty,
             "dirty_since": time.monotonic() if init_dirty else 0.0,
             "role_cache": {}, "trashed": trashed_now, "trashed_at": time.monotonic(),
             "text_len": text_len}
        rooms[doc_id] = r
    return r


def cached_role(r: dict, user: str, doc_id: str) -> str | None:
    now = time.monotonic()
    hit = r.get("role_cache", {}).get(user)
    if hit and now - hit[1] < CACHE_TTL:
        return hit[0]
    try:
        role = db.doc_role(user, doc_id)
    except Exception as e:
        log.warning("cached_role %s/%s failed: %s", doc_id, user, e)
        # Serve stale on transient DB failure when possible.
        return hit[0] if hit else None
    r.setdefault("role_cache", {})[user] = (role, now)
    return role


async def _role_async(r: dict, user: str, doc_id: str) -> str | None:
    """Cached role without blocking the loop (1C: to_thread on miss)."""
    now = time.monotonic()
    hit = r.get("role_cache", {}).get(user)
    if hit and now - hit[1] < CACHE_TTL:
        return hit[0]
    try:
        role = await asyncio.to_thread(db.doc_role, user, doc_id)
    except Exception as e:
        log.warning("role_async %s/%s failed: %s", doc_id, user, e)
        return hit[0] if hit else None
    r.setdefault("role_cache", {})[user] = (role, now)
    return role


def session_ok(token: str, user: str) -> str | None:
    now = time.monotonic()
    hit = _sess_cache.get(token)
    if hit and now - hit[1] < SESSION_RECHECK_TTL:
        return hit[0]
    try:
        current = auth.verify_session(token)
    except Exception as e:
        log.warning("session_ok verify failed: %s", e)
        return None
    _sess_cache[token] = (current, now)
    if len(_sess_cache) > 5000:
        _sess_cache.clear()
    return current


async def _session_async(token: str) -> str | None:
    """Cached session check without blocking the loop (1C)."""
    now = time.monotonic()
    hit = _sess_cache.get(token)
    if hit and now - hit[1] < SESSION_RECHECK_TTL:
        return hit[0]
    try:
        current = await asyncio.to_thread(auth.verify_session, token)
    except Exception as e:
        log.warning("session_async verify failed: %s", e)
        return hit[0] if hit else None
    _sess_cache[token] = (current, now)
    if len(_sess_cache) > 5000:
        _sess_cache.clear()
    return current


def fresh_trashed(doc_id: str) -> bool:
    try:
        return db.is_trashed(doc_id)
    except Exception as e:
        log.warning("trashed check failed for %s, keep open/dirty: %s", doc_id, e)
        return False


async def _trashed_async(doc_id: str, r: dict | None = None) -> bool:
    """Room-cached trash status without blocking the loop (1C)."""
    now = time.monotonic()
    if r is not None:
        if now - float(r.get("trashed_at", 0.0)) < TRASH_CACHE_TTL and "trashed" in r:
            return bool(r["trashed"])
    try:
        trashed = await asyncio.to_thread(db.is_trashed, doc_id)
    except Exception as e:
        log.warning("trashed_async failed for %s: %s", doc_id, e)
        if r is not None and "trashed" in r:
            return bool(r["trashed"])
        return False
    if r is not None:
        r["trashed"] = trashed
        r["trashed_at"] = now
    return trashed


def fresh_trashed_ok(doc_id: str) -> bool:
    # True when persisting is safe (doc not trashed).
    return not fresh_trashed(doc_id)


def drop_role_cache(username: str) -> None:
    # Drop cached roles for one user (share/unshare/rename).
    for r in rooms.values():
        r.get("role_cache", {}).pop(username, None)


def drop_sess_cache(username: str) -> None:
    # Drop cached session lookups for one user (logout/kick/rename).
    for tok, (u, _ts) in list(_sess_cache.items()):
        if u == username:
            _sess_cache.pop(tok, None)


def _drop_locks(doc_id: str) -> None:
    # Room gone: drop per-doc locks (lazy import keeps sync free of import cycles).
    try:
        from backend.services.locks import _drop_doc_locks
        _drop_doc_locks(doc_id)
    except Exception as e:
        log.warning("drop_locks %s failed: %s", doc_id, e)


def drop_sess_token(token: str) -> str | None:
    # Public API: drop one cached session token, return its user (logout path).
    hit = _sess_cache.pop(token, None)
    if hit and hit[0]:
        drop_sess_cache(hit[0])
        return hit[0]
    return hit[0] if hit else None


def invalidate_doc(doc_id: str) -> None:
    """Drop all cached WS state for a doc (1C: share/unshare/delete/trash).

    Track 1D: call this after share/unshare/delete/trash so rooms re-read
    role + trash status instead of serving stale caches. Current callers
    (share/unshare via drop_role_cache + kick_user, delete via drop) already
    invalidate through those paths; this is the explicit hook for new 1D
    writers that bypass them.
    """
    r = rooms.get(doc_id)
    if r is not None:
        r.get("role_cache", {}).clear()
        r.pop("trashed", None)
        r["trashed_at"] = 0.0


def invalidate_quota_cache(owner: str = "") -> None:
    """Drop quota cache entries (1C interface for track 1D).

    Track 1D: call invalidate_quota_cache(owner) after quota-relevant writes
    (avatar, files, templates) so the WS path re-reads instead of serving a
    stale over/under-quota verdict for up to QUOTA_CACHE_TTL.
    """
    if owner:
        _quota_cache.pop(owner, None)
    else:
        _quota_cache.clear()


def _ws_quota_ok(doc_id: str) -> bool:
    # Best-effort quota guard for WS autosave. Decoupled from backend.main:
    # owner + usage come from backend.services.quota (no lazy main import).
    # No lock: a stale True only delays the next periodic save; a stale
    # False keeps the room dirty and retries later.
    try:
        owner = _quota.doc_owner(doc_id, "")
    except Exception as e:
        log.warning("_ws_quota_ok owner failed for %s: %s", doc_id, e)
        return False
    if not owner:
        return False
    try:
        return not _quota.is_over_quota(owner)
    except Exception as e:
        log.warning("_ws_quota_ok check failed for %s: %s", doc_id, e)
        return False


async def _quota_ok_cached_async(doc_id: str) -> bool:
    """Short-lived quota cache in sync.py ONLY (1C).

    TTL = QUOTA_CACHE_TTL. Stale False keeps the room dirty and retries on
    the next flush; stale True only delays the next flush. Quota internals
    stay in services/quota.py (1D owns them).
    """
    try:
        owner = await asyncio.to_thread(_quota.doc_owner, doc_id, "")
    except Exception as e:
        log.warning("quota_async owner failed for %s: %s", doc_id, e)
        return False
    if not owner:
        return False
    now = time.monotonic()
    hit = _quota_cache.get(owner)
    if hit and now - hit[1] < QUOTA_CACHE_TTL:
        return not hit[0]
    try:
        over = await asyncio.to_thread(_quota.is_over_quota, owner)
    except Exception as e:
        log.warning("quota_async check failed for %s: %s", doc_id, e)
        return hit[0] is False if hit else False
    _quota_cache[owner] = (over, now)
    if len(_quota_cache) > 5000:
        _quota_cache.clear()
    return not over


def _size_ok(doc: Doc, payload: bytes, cached_len: int | None = None) -> bool:
    """Cheaper size gate replacing the per-update full doc copy (1C).

    Old path copied the whole doc (trial.apply_update(doc.get_update())) per
    keystroke. New path: one stringify of the live doc + payload-byte
    over-estimate; the exact trial copy runs only when near MAX_TXT (rare).
    Returns True when the update fits, False when it would exceed MAX_TXT.
    """
    try:
        if cached_len is not None and cached_len + len(payload) <= MAX_TXT:
            return True
        cur_len = len(str(doc.get("typst", type=Text)))
        # Fast path: current text + raw payload bytes still fit. Payload
        # bytes over-estimate added chars (Yjs metadata), so this never
        # falsely rejects small edits; near-limit edits fall through to the
        # exact check below.
        if cur_len + len(payload) <= MAX_TXT:
            return True
        # Near the limit: exact check via trial copy (rare).
        try:
            trial: Doc = Doc()
            trial.apply_update(doc.get_update())
            trial.apply_update(payload)
            exact = len(str(trial.get("typst", type=Text)))
        except Exception as e:
            log.warning("size check trial failed, reject: %s", e)
            return False
        return exact <= MAX_TXT
    except Exception as e:
        log.warning("size check failed, reject: %s", e)
        return False


def _mark_dirty(doc_id: str, r: dict) -> None:
    now = time.monotonic()
    r["dirty"] = True
    if not r.get("dirty_since"):
        r["dirty_since"] = now


async def _flush_one(doc_id: str, r: dict) -> bool:
    """Persist one dirty room via to_thread (flusher + disconnect path)."""
    if not r.get("dirty"):
        return True
    try:
        trashed = await _trashed_async(doc_id, r)
    except Exception as e:
        log.warning("flush_one %s trash check failed: %s", doc_id, e)
        return False
    if trashed:
        r["dirty"] = False
        r["dirty_since"] = 0.0
        return False
    try:
        ok = await _quota_ok_cached_async(doc_id)
    except Exception as e:
        log.warning("flush_one %s quota check failed: %s", doc_id, e)
        return False
    if not ok:
        return False  # over quota: keep dirty, retry on next flush
    try:
        yjs = await asyncio.to_thread(lambda: r["doc"].get_update())
        text = await asyncio.to_thread(lambda: str(r["doc"].get("typst", type=Text)))
        await asyncio.to_thread(db.save_room, doc_id, yjs, text)
    except Exception as e:
        log.warning("flush_one %s save failed: %s", doc_id, e)
        return False
    r["dirty"] = False
    r["dirty_since"] = 0.0
    r["saved"] = time.monotonic()
    try:
        r["text_len"] = len(text)
    except Exception as e:
        log.warning("flush_one %s text_len update failed: %s", doc_id, e)
    return True


async def _flusher_loop() -> None:
    try:
        while True:
            try:
                await asyncio.sleep(WRITE_BEHIND_FLUSH_SECONDS)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("flusher sleep failed: %s", e)
                break
            for doc_id, r in list(rooms.items()):
                if not r.get("dirty"):
                    continue
                try:
                    await _flush_one(doc_id, r)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    log.warning("flusher %s failed: %s", doc_id, e)
                if not r.get("conns") and not r.get("dirty"):
                    rooms.pop(doc_id, None)
                    _drop_locks(doc_id)
    except asyncio.CancelledError as e:
        log.debug("flusher loop cancelled: %s", e)
    except Exception as e:
        log.warning("flusher loop died: %s", e)


def ensure_flusher() -> None:
    """Start the write-behind flusher task once per loop (1C)."""
    global _flush_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as e:
        log.warning("ensure_flusher no running loop: %s", e)
        return
    if _flush_task is not None and not _flush_task.done():
        # Same loop? A task bound to a closed loop is done(); restart then.
        try:
            if _flush_task.get_loop() is loop:
                return
        except Exception as e:
            log.warning("ensure_flusher loop check failed: %s", e)
    try:
        _flush_task = loop.create_task(_flusher_loop(), name="sync-flusher")
    except Exception as e:
        log.warning("ensure_flusher start failed: %s", e)


_tasks: set = set()

async def bcast(conns: set, mine: WebSocket | None, data: bytes) -> None:
    async def send(c: WebSocket) -> None:
        try:
            await asyncio.wait_for(c.send_bytes(data), 5.0)
        except Exception as e:
            log.warning("bcast send failed, drop conn: %s", e)
            conns.discard(c)
            for r in rooms.values():
                try:
                    r.get("users", {}).pop(c, None)
                    r.get("tokens", {}).pop(c, None)
                    r.get("sess_at", {}).pop(c, None)
                except Exception as e:
                    log.warning("bcast cleanup failed: %s", e)
    for c in list(conns):
        if c is mine:
            continue
        t = asyncio.create_task(send(c))
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)


async def drop(doc_id: str) -> None:
    r = rooms.get(doc_id)
    if not r:
        return
    r.get("role_cache", {}).clear()
    r.pop("trashed", None)
    r["trashed_at"] = 0.0
    if r.get("dirty"):
        try:
            trashed = await _trashed_async(doc_id, None)
        except Exception as e:
            log.warning("drop %s trash check failed: %s", doc_id, e)
            trashed = False
        if trashed:
            r["dirty"] = False  # trashed: skip persist into trashed doc
        else:
            try:
                yjs = await asyncio.to_thread(lambda: r["doc"].get_update())
                text = await asyncio.to_thread(lambda: str(r["doc"].get("typst", type=Text)))
                await asyncio.to_thread(db.save_room, doc_id, yjs, text)
                r["dirty"] = False
                r["saved"] = time.monotonic()
            except Exception as e:
                log.warning("drop %s: save failed: %s", doc_id, e)
                r["dirty"] = True
                return
    rooms.pop(doc_id, None)
    _drop_locks(doc_id)
    for c in list(r["conns"]):
        try:
            await c.close(code=4403)
        except Exception as e:
            log.warning("drop %s: close failed: %s", doc_id, e)


async def kick_user(doc_id: str, username: str) -> None:
    r = rooms.get(doc_id)
    if not r:
        return
    for c in list(r["conns"]):
        if r.get("users", {}).get(c) == username:
            try:
                await c.close(code=4403)
            except Exception as e:
                log.warning("kick_user %s: close failed: %s", doc_id, e)
            r["conns"].discard(c)
            r.get("users", {}).pop(c, None)
            r.get("tokens", {}).pop(c, None)
            r.get("sess_at", {}).pop(c, None)
    r.get("role_cache", {}).pop(username, None)
    # Share/unshare invalidation (1C): force trash re-read for remaining
    # conns (role change never implies trash change, but re-read is cheap
    # and keeps drop_role_cache/kick_user/drop coherent; delete path uses
    # drop() which already clears trash).
    r.pop("trashed", None)
    r["trashed_at"] = 0.0
    if not r["conns"]:
        if r.get("dirty"):
            try:
                trashed = await _trashed_async(doc_id, None)
            except Exception as e:
                log.warning("kick_user %s trash check failed: %s", doc_id, e)
                trashed = False
            if trashed:
                r["dirty"] = False  # trashed: skip persist into trashed doc
            else:
                try:
                    yjs = await asyncio.to_thread(lambda: r["doc"].get_update())
                    text = await asyncio.to_thread(lambda: str(r["doc"].get("typst", type=Text)))
                    await asyncio.to_thread(db.save_room, doc_id, yjs, text)
                    r["dirty"] = False
                    r["saved"] = time.monotonic()
                except Exception as e:
                    log.warning("kick_user %s: save failed: %s", doc_id, e)
                    return
            rooms.pop(doc_id, None)
            _drop_locks(doc_id)


async def kick_all(username: str) -> None:
    drop_sess_cache(username)
    for doc_id in list(rooms):
        await kick_user(doc_id, username)


def persist(doc_id: str) -> bool:
    r = rooms.get(doc_id)
    if not r:
        return False
    if not fresh_trashed_ok(doc_id):
        r["dirty"] = False  # trashed: skip persist into trashed doc
        return False
    try:
        db.save_room(doc_id, r["doc"].get_update(), str(r["doc"].get("typst", type=Text)))
        r["dirty"] = False
        r["dirty_since"] = 0.0
        r["saved"] = time.monotonic()
    except Exception as e:
        log.warning("persist %s: save failed: %s", doc_id, e)
        r["dirty"] = True
        return False
    return True


def flush_all() -> None:
    for doc_id, r in list(rooms.items()):
        if not r.get("dirty"):
            continue
        if not fresh_trashed_ok(doc_id):
            r["dirty"] = False  # trashed: skip persist into trashed doc
            continue
        try:
            db.save_room(doc_id, r["doc"].get_update(), str(r["doc"].get("typst", type=Text)))
            r["dirty"] = False
            r["dirty_since"] = 0.0
            r["saved"] = time.monotonic()
        except Exception as e:
            log.warning("flush_all %s: save failed: %s", doc_id, e)


def room_text(doc_id: str) -> str | None:
    r = rooms.get(doc_id)
    if not r:
        return None
    try:
        return str(r["doc"].get("typst", type=Text))
    except Exception as e:
        log.warning("room_text %s failed: %s", doc_id, e)
        return None


async def replace_text(doc_id: str, content: str) -> None:
    r = rooms.get(doc_id)
    if not r:
        try:
            await asyncio.to_thread(db.clear_room_state, doc_id)
        except Exception as e:
            log.warning("replace_text %s: clear_room_state failed: %s", doc_id, e)
        return
    doc: Doc = r["doc"]
    try:
        with doc.transaction():
            text = doc.get("typst", type=Text)
            text.clear()
            text += content
    except Exception as e:
        log.warning("replace_text %s: apply failed: %s", doc_id, e)
        return
    try:
        r["text_len"] = len(content)
    except Exception as e:
        log.warning("replace_text %s text_len failed: %s", doc_id, e)
    try:
        trashed = await _trashed_async(doc_id, r)
    except Exception as e:
        log.warning("replace_text %s trash check failed: %s", doc_id, e)
        trashed = False
    if trashed:
        r["dirty"] = True  # trashed: skip persist into trashed doc
    else:
        try:
            yjs = await asyncio.to_thread(doc.get_update)
            await asyncio.to_thread(db.save_room, doc_id, yjs, content)
            r["dirty"] = False
            r["dirty_since"] = 0.0
            r["saved"] = time.monotonic()
        except Exception as e:
            log.warning("replace_text %s: save failed: %s", doc_id, e)
            r["dirty"] = True
    update = doc.get_update()
    await bcast(r["conns"], None, blob(write_var(MSG_SYNC), write_var(UPDATE),
                                       write_var(len(update)), update))


async def _close(ws: WebSocket, doc_id: str, code: int, why: str) -> None:
    try:
        await ws.close(code=code)
    except Exception as e:
        log.warning("handle %s: close after %s failed: %s", doc_id, why, e)


async def handle(ws: WebSocket, doc_id: str) -> None:
    # 1C: no synchronous DB on the event loop. Every DB touch below goes
    # through asyncio.to_thread (directly or via the _*_async helpers that
    # serve room-cached role/trash/session first).
    token = ws.cookies.get(COOKIE, "")
    try:
        user = await asyncio.to_thread(auth.verify_session, token)
        role = await asyncio.to_thread(db.doc_role, user or "", doc_id) if user else None
        trashed = await asyncio.to_thread(db.is_trashed, doc_id) if role else True
    except sqlite3.OperationalError as e:
        log.warning("handle %s: initial check busy: %s", doc_id, e)
        await ws.accept()
        await _close(ws, doc_id, 1011, "busy")
        return
    except Exception as e:
        log.warning("handle %s: initial check failed: %s", doc_id, e)
        await ws.accept()
        await _close(ws, doc_id, 1011, "init-fail")
        return
    if not role or trashed:
        await ws.accept()
        await _close(ws, doc_id, 4403, "no-access")
        return
    await ws.accept()
    origin = ws.headers.get("origin", "") or ws.headers.get("referer", "")
    host = ws.headers.get("host", "")
    if origin and urlparse(origin).netloc.lower() != host.split(",")[-1].strip().lower():
        await _close(ws, doc_id, 4403, "origin")
        return
    try:
        r = await asyncio.to_thread(room, doc_id)
    except sqlite3.OperationalError as e:
        log.warning("handle %s: room load busy: %s", doc_id, e)
        await _close(ws, doc_id, 1011, "room-busy")
        return
    except Exception as e:
        log.warning("handle %s: room load failed: %s", doc_id, e)
        await _close(ws, doc_id, 1011, "room-fail")
        return
    doc: Doc = r["doc"]
    # Hold role, trash status and session in room state (1C): users/tokens/
    # sess_at bind each WS to its user + token + last check (used for precise
    # cleanup on bcast-fail/kick/disconnect; the session verdict itself comes
    # from the shared _sess_cache in sync.py via _session_async, invalidated
    # on logout/kick/rename so revoked tokens die on next message).
    r["conns"].add(ws)
    r.setdefault("users", {})[ws] = user
    r.setdefault("tokens", {})[ws] = token
    r.setdefault("sess_at", {})[ws] = time.monotonic()
    r.setdefault("role_cache", {})[user or ""] = (role, time.monotonic())
    r["trashed"] = bool(trashed)
    r["trashed_at"] = time.monotonic()
    ensure_flusher()
    aware_n = 0
    aware_win = time.monotonic()
    try:
        try:
            sv = doc.get_state()
        except Exception as e:
            log.warning("handle %s: get_state failed: %s", doc_id, e)
            await _close(ws, doc_id, 1011, "state")
            return
        try:
            await ws.send_bytes(blob(write_var(MSG_SYNC), write_var(STEP1),
                                     write_var(len(sv)), sv))
        except Exception as e:
            log.warning("handle %s: step1 send failed: %s", doc_id, e)
            return
        while True:
            try:
                data = await ws.receive_bytes()
            except (WebSocketDisconnect, RuntimeError) as e:
                log.debug("handle %s: disconnect during receive: %s", doc_id, e)
                break
            except Exception as e:
                log.warning("handle %s: receive failed: %s", doc_id, e)
                break
            # 1C: parse first (sync, no yield) so UPDATE stays atomic.
            # Fresh trash revalidation happens on STEP1 (no mutate yet, yield
            # safe); UPDATE uses room-cached trash/role/session only (no DB
            # when caches are fresh -> no yield -> no cancellation loss on
            # close races, no loop blocker under load). API mutations
            # (share/unshare/delete/logout) already kick/close + invalidate,
            # so cached verdicts here are safe.
            if len(data) > 2 * 1024 * 1024:
                await _close(ws, doc_id, 4409, "oversize-payload")
                break
            try:
                t, p = read_var(data, 0)
            except (ValueError, IndexError) as e:
                log.debug("handle %s: bad varint, skip: %s", doc_id, e)
                continue
            if t == MSG_SYNC:
                try:
                    st, p = read_var(data, p)
                    ln, p = read_var(data, p)
                except (ValueError, IndexError) as e:
                    log.debug("handle %s: bad sync header, skip: %s", doc_id, e)
                    continue
                if ln < 0 or p + ln > len(data):
                    continue
                payload = data[p:p + ln]
                if st == STEP1:
                    # Fresh trash here (yield safe, no mutate yet). This is
                    # what kicks trashed-doc connections promptly.
                    if await _trashed_async(doc_id, r):
                        await _close(ws, doc_id, 4403, "trash")
                        break
                    sess = await _session_async(token)
                    if sess is None:
                        await _close(ws, doc_id, 4403, "session-expiry")
                        break
                    role_now = await _role_async(r, user or "", doc_id)
                    if not role_now:
                        await _close(ws, doc_id, 4403, "role-loss")
                        break
                    try:
                        diff = doc.get_update(payload)
                    except Exception as e:
                        log.warning("handle %s: step1 diff failed: %s", doc_id, e)
                        continue
                    try:
                        await ws.send_bytes(blob(write_var(MSG_SYNC), write_var(STEP2),
                                                 write_var(len(diff)), diff))
                    except Exception as e:
                        log.warning("handle %s: step2 send failed: %s", doc_id, e)
                        break
                elif st in (STEP2, UPDATE) and payload:
                    # Hot path: cached-only guards (no DB when fresh -> no
                    # yield -> atomic apply, no cancellation loss, no blocker).
                    sess = await _session_async(token)
                    if sess is None:
                        await _close(ws, doc_id, 4403, "session-expiry")
                        break
                    role_now = await _role_async(r, user or "", doc_id)
                    if not role_now or r.get("trashed", False):
                        await _close(ws, doc_id, 4403, "role-loss")
                        break
                    if role_now == "reviewer":
                        continue
                    # 1C: cheaper size gate (no full doc copy unless near limit).
                    if not _size_ok(doc, payload, r.get("text_len")):
                        await _close(ws, doc_id, 4409, "MAX_TXT")
                        break
                    try:
                        doc.apply_update(payload)
                    except Exception as e:
                        log.warning("handle %s: apply_update failed: %s", doc_id, e)
                        continue
                    try:
                        r["text_len"] = len(str(doc.get("typst", type=Text)))
                    except Exception as e:
                        log.warning("handle %s: text_len update failed: %s", doc_id, e)
                    # 1C write-behind: mark dirty only. The flusher persists
                    # every WRITE_BEHIND_FLUSH_SECONDS; the final disconnect
                    # below flushes immediately. No DB here.
                    _mark_dirty(doc_id, r)
                    try:
                        await bcast(r["conns"], ws, blob(write_var(MSG_SYNC), write_var(UPDATE),
                                                         write_var(len(payload)), payload))
                    except Exception as e:
                        log.warning("handle %s: bcast failed: %s", doc_id, e)
            elif t == MSG_AWARENESS:
                if len(data) > AWARE_MAX:
                    continue
                _now = time.monotonic()
                if _now - aware_win >= 1.0:
                    aware_win, aware_n = _now, 0
                aware_n += 1
                if aware_n > 60:
                    continue  # awareness flood: drop, keep connection
                sess = await _session_async(token)
                if sess is None:
                    await _close(ws, doc_id, 4403, "session-expiry")
                    break
                role_now = await _role_async(r, user or "", doc_id)
                if not role_now or r.get("trashed", False):
                    await _close(ws, doc_id, 4403, "role-loss")
                    break
                try:
                    await bcast(r["conns"], ws, data)
                except Exception as e:
                    log.warning("handle %s: awareness bcast failed: %s", doc_id, e)
    except sqlite3.OperationalError as e:
        log.warning("handle %s: loop busy: %s", doc_id, e)
        await _close(ws, doc_id, 1011, "loop-busy")
    except (WebSocketDisconnect, RuntimeError) as e:
        log.debug("handle %s: disconnect: %s", doc_id, e)
    except Exception as e:
        log.warning("handle %s: loop failed: %s", doc_id, e)
    finally:
        try:
            r["conns"].discard(ws)
        except Exception as e:
            log.warning("handle %s: conns discard failed: %s", doc_id, e)
        for _map in ("users", "tokens", "sess_at"):
            try:
                r.get(_map, {}).pop(ws, None)
            except Exception as e:
                log.warning("handle %s: %s cleanup failed: %s", doc_id, _map, e)
        # 1C write-behind: flush on last disconnect. Sync here (not
        # to_thread): teardown must not yield indefinitely — the per-message
        # hot path already avoids DB (marks dirty only), so the loop-blocker
        # goal holds. Like the pre-1C finally this persists unless trashed
        # (no quota check: the flusher respects quota via _quota_ok_cached,
        # but a close never silently drops the final keystrokes).
        # Loss window = WRITE_BEHIND_FLUSH_SECONDS.
        if r.get("dirty"):
            try:
                if not persist(doc_id):
                    # Trashed/busy: keep dirty for the flusher retry.
                    pass
            except Exception as e:
                log.warning("handle %s: final flush failed: %s", doc_id, e)
                r["dirty"] = True
        if not r["conns"] and not r.get("dirty"):
            rooms.pop(doc_id, None)
            _drop_locks(doc_id)
