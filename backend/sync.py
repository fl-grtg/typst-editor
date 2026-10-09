"""Yjs-compatible sync server in Python (pycrdt)."""
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
from backend.constants import AWARE_MAX, CACHE_TTL, MAX_TXT, ROOMS_MAX, SAVE_EVERY, SESSION_RECHECK_TTL
from backend.services import quota as _quota

log = logging.getLogger("typst.sync")

COOKIE = auth.COOKIE

MSG_SYNC = 0
MSG_AWARENESS = 1
STEP1 = 0
STEP2 = 1
UPDATE = 2

rooms: dict[str, dict] = {}
_sess_cache: dict[str, tuple[str | None, float]] = {}


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
        r = {"doc": doc, "conns": set(), "users": {}, "saved": 0.0, "dirty": init_dirty,
             "role_cache": {}}
        rooms[doc_id] = r
    return r


def cached_role(r: dict, user: str, doc_id: str) -> str | None:
    now = time.monotonic()
    hit = r.get("role_cache", {}).get(user)
    if hit and now - hit[1] < CACHE_TTL:
        return hit[0]
    role = db.doc_role(user, doc_id)
    r.setdefault("role_cache", {})[user] = (role, now)
    return role


def session_ok(token: str, user: str) -> str | None:
    now = time.monotonic()
    hit = _sess_cache.get(token)
    if hit and now - hit[1] < SESSION_RECHECK_TTL:
        return hit[0]
    try:
        current = auth.verify_session(token)
    except Exception:
        return None
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
    except Exception:
        pass


def drop_sess_token(token: str) -> str | None:
    # Public API: drop one cached session token, return its user (logout path).
    hit = _sess_cache.pop(token, None)
    if hit and hit[0]:
        drop_sess_cache(hit[0])
        return hit[0]
    return hit[0] if hit else None


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


_tasks: set = set()

async def bcast(conns: set, mine: WebSocket | None, data: bytes) -> None:
    async def send(c: WebSocket) -> None:
        try:
            await asyncio.wait_for(c.send_bytes(data), 5.0)
        except Exception:
            conns.discard(c)
            for r in rooms.values():
                r.get("users", {}).pop(c, None)
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
    if r.get("dirty"):
        if not fresh_trashed_ok(doc_id):
            r["dirty"] = False  # trashed: skip persist into trashed doc
        else:
            try:
                db.save_room(doc_id, r["doc"].get_update(), str(r["doc"].get("typst", type=Text)))
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
    r.get("role_cache", {}).pop(username, None)
    if not r["conns"]:
        if r.get("dirty"):
            if not fresh_trashed_ok(doc_id):
                r["dirty"] = False  # trashed: skip persist into trashed doc
            else:
                try:
                    db.save_room(doc_id, r["doc"].get_update(), str(r["doc"].get("typst", type=Text)))
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
            r["saved"] = time.monotonic()
        except Exception as e:
            log.warning("flush_all %s: save failed: %s", doc_id, e)


def room_text(doc_id: str) -> str | None:
    r = rooms.get(doc_id)
    if not r:
        return None
    try:
        return str(r["doc"].get("typst", type=Text))
    except Exception:
        return None


async def replace_text(doc_id: str, content: str) -> None:
    r = rooms.get(doc_id)
    if not r:
        try:
            db.clear_room_state(doc_id)
        except Exception as e:
            log.warning("replace_text %s: clear_room_state failed: %s", doc_id, e)
        return
    doc: Doc = r["doc"]
    with doc.transaction():
        text = doc.get("typst", type=Text)
        text.clear()
        text += content
    if not fresh_trashed_ok(doc_id):
        r["dirty"] = True  # trashed: skip persist into trashed doc
    else:
        try:
            db.save_room(doc_id, doc.get_update(), content)
            r["dirty"] = False
            r["saved"] = time.monotonic()
        except Exception as e:
            log.warning("replace_text %s: save failed: %s", doc_id, e)
            r["dirty"] = True
    update = doc.get_update()
    await bcast(r["conns"], None, blob(write_var(MSG_SYNC), write_var(UPDATE),
                                       write_var(len(update)), update))


async def handle(ws: WebSocket, doc_id: str) -> None:
    token = ws.cookies.get(COOKIE, "")
    try:
        user = auth.verify_session(token)
        role = db.doc_role(user or "", doc_id) if user else None
        trashed = db.is_trashed(doc_id) if role else True
    except sqlite3.OperationalError:
        await ws.accept()
        await ws.close(code=1011)
        return
    if not role or trashed:
        await ws.accept()
        await ws.close(code=4403)
        return
    await ws.accept()
    origin = ws.headers.get("origin", "") or ws.headers.get("referer", "")
    host = ws.headers.get("host", "")
    if origin and urlparse(origin).netloc.lower() != host.split(",")[-1].strip().lower():
        await ws.close(code=4403)
        return
    try:
        r = room(doc_id)
    except sqlite3.OperationalError:
        try:
            await ws.close(code=1011)
        except Exception:
            pass
        return
    doc: Doc = r["doc"]
    r["conns"].add(ws)
    r.setdefault("users", {})[ws] = user
    aware_n = 0
    aware_win = time.monotonic()
    try:
        sv = doc.get_state()
        await ws.send_bytes(blob(write_var(MSG_SYNC), write_var(STEP1),
                                 write_var(len(sv)), sv))
        while True:
            data = await ws.receive_bytes()
            if fresh_trashed(doc_id):
                try:
                    await ws.close(code=4403)
                except Exception as e:
                    log.warning("handle %s: close after trash failed: %s", doc_id, e)
                break
            if len(data) > 2 * 1024 * 1024:
                try:
                    await ws.close(code=4409)
                except Exception as e:
                    log.warning("handle %s: close after oversize payload failed: %s", doc_id, e)
                break
            try:
                t, p = read_var(data, 0)
            except (ValueError, IndexError):
                continue
            if t == MSG_SYNC:
                try:
                    st, p = read_var(data, p)
                    ln, p = read_var(data, p)
                except (ValueError, IndexError):
                    continue
                if ln < 0 or p + ln > len(data):
                    continue
                payload = data[p:p + ln]
                if st == STEP1:
                    if session_ok(token, user or "") is None:
                        try:
                            await ws.close(code=4403)
                        except Exception as e:
                            log.warning("handle %s: close after session expiry failed: %s", doc_id, e)
                        break
                    role_now = cached_role(r, user or "", doc_id)
                    if not role_now or fresh_trashed(doc_id):
                        try:
                            await ws.close(code=4403)
                        except Exception as e:
                            log.warning("handle %s: close after role loss failed: %s", doc_id, e)
                        break
                    try:
                        diff = doc.get_update(payload)
                    except Exception:
                        continue
                    await ws.send_bytes(blob(write_var(MSG_SYNC), write_var(STEP2),
                                             write_var(len(diff)), diff))
                elif st in (STEP2, UPDATE) and payload:
                    if session_ok(token, user or "") is None:
                        try:
                            await ws.close(code=4403)
                        except Exception as e:
                            log.warning("handle %s: close after session expiry failed: %s", doc_id, e)
                        break
                    role_now = cached_role(r, user or "", doc_id)
                    if not role_now or fresh_trashed(doc_id):
                        try:
                            await ws.close(code=4403)
                        except Exception as e:
                            log.warning("handle %s: close after role loss failed: %s", doc_id, e)
                        break
                    if role_now == "reviewer":
                        continue
                    try:
                        trial: Doc = Doc()
                        trial.apply_update(doc.get_update())
                        trial.apply_update(payload)
                        cur_len = len(str(trial.get("typst", type=Text)))
                    except Exception:
                        continue
                    if cur_len > MAX_TXT:
                        try:
                            await ws.close(code=4409)
                        except Exception as e:
                            log.warning("handle %s: close after MAX_TXT failed: %s", doc_id, e)
                        break
                    doc.apply_update(payload)
                    now = time.monotonic()
                    if now - r.get("saved", 0.0) >= SAVE_EVERY:
                        if not fresh_trashed_ok(doc_id):
                            r["dirty"] = False  # trashed: skip persist into trashed doc
                        elif not _ws_quota_ok(doc_id):
                            r["dirty"] = True  # over quota: keep dirty, retry later
                        else:
                            try:
                                db.save_room(doc_id, doc.get_update(), str(doc.get("typst", type=Text)))
                                r["saved"] = now
                                r["dirty"] = False
                            except Exception as e:
                                log.warning("handle %s: periodic save failed: %s", doc_id, e)
                                r["dirty"] = True
                    else:
                        r["dirty"] = True
                    await bcast(r["conns"], ws, blob(write_var(MSG_SYNC), write_var(UPDATE),
                                                     write_var(len(payload)), payload))
            elif t == MSG_AWARENESS:
                if len(data) > AWARE_MAX:
                    continue
                _now = time.monotonic()
                if _now - aware_win >= 1.0:
                    aware_win, aware_n = _now, 0
                aware_n += 1
                if aware_n > 60:
                    continue  # awareness flood: drop, keep connection
                if session_ok(token, user or "") is None:
                    try:
                        await ws.close(code=4403)
                    except Exception as e:
                        log.warning("handle %s: close after session expiry failed: %s", doc_id, e)
                    break
                role_now = cached_role(r, user or "", doc_id)
                if not role_now or fresh_trashed(doc_id):
                    try:
                        await ws.close(code=4403)
                    except Exception as e:
                        log.warning("handle %s: close after role loss failed: %s", doc_id, e)
                    break
                try:
                    await bcast(r["conns"], ws, data)
                except Exception as e:
                    log.warning("handle %s: awareness bcast failed: %s", doc_id, e)
    except sqlite3.OperationalError:
        try:
            await ws.close(code=1011)
        except Exception:
            pass
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        r["conns"].discard(ws)
        r.get("users", {}).pop(ws, None)
        if r.get("dirty"):
            if not fresh_trashed_ok(doc_id):
                r["dirty"] = False  # trashed: skip persist into trashed doc
            else:
                try:
                    db.save_room(doc_id, doc.get_update(), str(doc.get("typst", type=Text)))
                    r["dirty"] = False
                    r["saved"] = time.monotonic()
                except Exception as e:
                    log.warning("handle %s: final save failed: %s", doc_id, e)
                    r["dirty"] = True
        if not r["conns"] and not r.get("dirty"):
            rooms.pop(doc_id, None)
            _drop_locks(doc_id)
