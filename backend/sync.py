"""Yjs-kompatibler Sync-Server direkt in Python (pycrdt).

Ersetzt den alten Node-Prozess: ein Prozess, ein Port, DB-Zugriff direkt.
Protokoll wie y-websocket (Client <-> Server):
  [0, 0, sv]  Client-Step1 -> Server antwortet [0, 1, diff]
  [0, 1|2, u] Client-Diff/Update -> anwenden + an andere weiterreichen
  [1, ...]    Awareness -> nur weiterreichen (kein Server-State nötig)
Reviewer bekommen alles live, ihre Updates werden verworfen.
"""
from __future__ import annotations

import asyncio
import time

from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect
from pycrdt import Doc, Text

from backend import auth, db

SAVE_EVERY = 2.0  # DB-Write höchstens alle 2s pro Room (Tippen sonst = Dauerfeuer)
MAX_TXT = 200_000  # Duplikat aus backend.main (kein Import: main importiert sync -> Zyklus)
AWARE_MAX = 64 * 1024  # Awareness ist nur Cursor-Deko: größer wird gedroppt
CACHE_TTL = 10.0  # Rollen/Trash-Cache pro Room: DB nur bei Ablauf neu lesen

COOKIE = auth.COOKIE  # Session-Name (eine Quelle in auth)

MSG_SYNC = 0
MSG_AWARENESS = 1
STEP1 = 0
STEP2 = 1
UPDATE = 2

rooms: dict[str, dict] = {}  # doc_id -> {"doc": Doc, "conns": set[WebSocket]}


def read_var(data: bytes, pos: int) -> tuple[int, int]:
    n = s = 0
    while True:
        if pos >= len(data):
            raise ValueError("kurz")
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
        doc = Doc()
        yjs, content = db.get_room_state(doc_id)
        if yjs:
            try:
                doc.apply_update(yjs)  # gleiche IDs wie vorher: Sync ist idempotent
            except Exception:
                doc = Doc()  # korruptes yjs: aus content neu aufbauen statt Crash + hängende WS
                if content:
                    with doc.transaction():
                        text = doc.get("typst", type=Text)
                        text += content
                try:
                    db.save_room(doc_id, doc.get_update(), content)
                except Exception:
                    pass
        elif content:
            with doc.transaction():
                text = doc.get("typst", type=Text)
                text += content  # Alt-Bestand ohne Bytes: einmalig, danach Bytes sichern
            db.save_room(doc_id, doc.get_update(), content)
        r = {"doc": doc, "conns": set(), "users": {}, "saved": 0.0, "dirty": False,
             "role_cache": {}, "trashed_cache": (False, 0.0)}
        rooms[doc_id] = r
    return r


def cached_role(r: dict, user: str, doc_id: str) -> str | None:
    """Rolle pro Keystroke aus dem Cache (TTL 10s): Downgrade wirkt verzögert, Unshare kickt sofort."""
    now = time.monotonic()
    hit = r.get("role_cache", {}).get(user)
    if hit and now - hit[1] < CACHE_TTL:
        return hit[0]
    role = db.doc_role(user, doc_id)
    r.setdefault("role_cache", {})[user] = (role, now)
    return role


def cached_trashed(r: dict, doc_id: str) -> bool:
    now = time.monotonic()
    val, ts = r.get("trashed_cache", (False, 0.0))
    if now - ts < CACHE_TTL:
        return val
    val = db.is_trashed(doc_id)
    r["trashed_cache"] = (val, now)
    return val


async def bcast(conns: set, mine: WebSocket, data: bytes) -> None:
    for c in list(conns):
        if c is mine:
            continue
        try:
            await asyncio.wait_for(c.send_bytes(data), 5.0)  # langsamster Client blockiert nicht alle
        except Exception:
            conns.discard(c)  # tot/langsam: beim nächsten Close komplett weg


async def drop(doc_id: str) -> None:  # Room weg (Trash/Delete): sichern, poppen, Sockets zu
    r = rooms.get(doc_id)
    if not r:
        return
    if r.get("dirty"):
        try:
            db.save_room(doc_id, r["doc"].get_update(), str(r["doc"].get("typst", type=Text)))
        except Exception:
            pass
    rooms.pop(doc_id, None)
    for c in list(r["conns"]):
        try:
            await c.close(code=4403)
        except Exception:
            pass


async def kick_user(doc_id: str, username: str) -> None:
    r = rooms.get(doc_id)
    if not r:
        return
    for c in list(r["conns"]):
        if r.get("users", {}).get(c) == username:
            try:
                await c.close(code=4403)
            except Exception:
                pass
            r["conns"].discard(c)
            r.get("users", {}).pop(c, None)
    r.get("role_cache", {}).pop(username, None)  # Cache weg: Rejoin liest die Rolle frisch
    if not r["conns"]:
        rooms.pop(doc_id, None)  # leer: kein Memory-Leak


def persist(doc_id: str) -> bool:  # HTTP-Save: Bytes sofort sichern (sonst Neustart-Fenster)
    r = rooms.get(doc_id)
    if not r:
        return False
    try:
        db.save_room(doc_id, r["doc"].get_update(), str(r["doc"].get("typst", type=Text)))
        r["dirty"] = False
        r["saved"] = time.monotonic()  # sonst spart persist nichts: nächster Keystroke speichert doppelt
    except Exception:
        r["dirty"] = True
    return True


def flush_all() -> None:  # Shutdown: alle dirty Rooms sichern, Fehler schlucken
    for doc_id, r in list(rooms.items()):
        if not r.get("dirty"):
            continue
        try:
            db.save_room(doc_id, r["doc"].get_update(), str(r["doc"].get("typst", type=Text)))
            r["dirty"] = False
            r["saved"] = time.monotonic()
        except Exception:
            pass


def room_text(doc_id: str) -> str | None:  # neuster Stand aus dem Live-Room (None = keiner da)
    r = rooms.get(doc_id)
    if not r:
        return None
    try:
        return str(r["doc"].get("typst", type=Text))
    except Exception:
        return None


async def replace_text(doc_id: str, content: str) -> None:  # Verlauf-Restore: Room füllen + an alle funken
    r = rooms.get(doc_id)
    if not r:
        db.clear_room_state(doc_id)  # keiner verbunden: Bytes weg, Room baut aus content neu
        return
    doc: Doc = r["doc"]
    with doc.transaction():
        text = doc.get("typst", type=Text)
        text.clear()
        text += content
    db.save_room(doc_id, doc.get_update(), content)
    r["dirty"] = False
    update = doc.get_update()  # Voll-Update: idempotent, kommt bei allen an (Restore ist selten)
    await bcast(r["conns"], None, blob(write_var(MSG_SYNC), write_var(UPDATE),
                                       write_var(len(update)), update))


async def handle(ws: WebSocket, doc_id: str) -> None:
    token = ws.query_params.get("token", "") or ws.cookies.get(COOKIE, "")
    user = auth.verify_session(token)
    role = db.doc_role(user or "", doc_id) if user else None
    if not role or db.is_trashed(doc_id):
        await ws.accept()
        await ws.close(code=4403)  # kein Zugriff: erst annehmen, dann mit Code schließen
        return
    await ws.accept()
    r = room(doc_id)  # Rolle steht pro Nachricht neu drin (Unshare/Downgrade kickt beim Tippen)
    doc: Doc = r["doc"]
    r["conns"].add(ws)
    r.setdefault("users", {})[ws] = user
    try:
        sv = doc.get_state()  # eigener Step1 zuerst, wie y-websocket
        await ws.send_bytes(blob(write_var(MSG_SYNC), write_var(STEP1),
                                 write_var(len(sv)), sv))
        while True:
            data = await ws.receive_bytes()
            if cached_trashed(r, doc_id):
                try:
                    await ws.close(code=4403)
                except Exception:
                    pass
                break  # zwischenzeitlich in Papierkorb: kein Geist-Tippen, Room macht zu
            if len(data) > 2 * 1024 * 1024:
                try:
                    await ws.close(code=4409)
                except Exception:
                    pass
                break  # Riesen-Payload: kein RAM-DoS, sauber zu
            try:
                t, p = read_var(data, 0)
            except (ValueError, IndexError):
                continue  # kaputter Frame: ignorieren, Verbindung lebt
            if t == MSG_SYNC:
                try:
                    st, p = read_var(data, p)
                    ln, p = read_var(data, p)
                except (ValueError, IndexError):
                    continue
                if ln < 0 or p + ln > len(data):
                    continue  # Länge passt nicht zum Frame: ignorieren statt crashen
                payload = data[p:p + ln]
                if st == STEP1:
                    try:
                        diff = doc.get_update(payload)
                    except Exception:
                        continue
                    await ws.send_bytes(blob(write_var(MSG_SYNC), write_var(STEP2),
                                             write_var(len(diff)), diff))
                elif st in (STEP2, UPDATE) and payload:
                    role_now = cached_role(r, user or "", doc_id)  # Unshare/Downgrade kickt beim nächsten Tippen
                    if not role_now or cached_trashed(r, doc_id):
                        try:
                            await ws.close(code=4403)
                        except Exception:
                            pass
                        break
                    if role_now == "reviewer":
                        continue  # runtergestuft: parsen, aber verwerfen
                    try:  # erst probieren: kaputtes Update wirft, Room bleibt sauber
                        trial = Doc()
                        trial.apply_update(doc.get_update())
                        trial.apply_update(payload)
                        cur_len = len(str(trial.get("typst", type=Text)))
                    except Exception:
                        continue  # kaputtes Update: ignorieren, Verbindung lebt
                    if cur_len > MAX_TXT:  # aufgebläht: weder speichern noch funken, Verursacher raus
                        try:
                            await ws.close(code=4409)
                        except Exception:
                            pass
                        break
                    doc.apply_update(payload)  # Trial war ok: jetzt echt uebernehmen
                    now = time.monotonic()  # bündeln: Text sofort weiter, DB höchstens alle SAVE_EVERY
                    if now - r.get("saved", 0.0) >= SAVE_EVERY:
                        try:
                            db.save_room(doc_id, doc.get_update(), str(doc.get("typst", type=Text)))
                            r["saved"] = now
                            r["dirty"] = False
                        except Exception:
                            r["dirty"] = True
                    else:
                        r["dirty"] = True
                    await bcast(r["conns"], ws, blob(write_var(MSG_SYNC), write_var(UPDATE),
                                                     write_var(len(payload)), payload))
                # Reviewer-Update: parsen, aber verwerfen
            elif t == MSG_AWARENESS:
                if len(data) > AWARE_MAX:
                    continue  # Riesen-Cursor: droppen statt an alle funken
                try:
                    await bcast(r["conns"], ws, data)
                except Exception:
                    pass
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        r["conns"].discard(ws)
        r.get("users", {}).pop(ws, None)
        if r.get("dirty"):  # Rest sichern, bevor der Room zugeht
            try:
                db.save_room(doc_id, doc.get_update(), str(doc.get("typst", type=Text)))
            except Exception:
                pass
            r["dirty"] = False
        if not r["conns"]:
            rooms.pop(doc_id, None)
