from __future__ import annotations

import base64
import io
import re
import shutil
import sqlite3
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, UploadFile, WebSocket, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from backend import auth, config, db, ratelimit, sync

COOKIE = auth.COOKIE
NAME_RE = r"[A-Za-z0-9_-]{2,20}"  # Usernamen: 2-20 Zeichen, ohne Leerzeichen
MIN_PW = 8
MAX_PW = 200  # Passwort-Deckel (KDF-DoS)
MAX_TXT = 200_000  # Text-Limit (Template, Datei-Tab, Starter)
TITLE_MAX = 100  # Doc-Titel: lesbar bleiben
FOLDER_MAX = 40  # Ordnername: kurz halten (Sidebar)
SNAP_EVERY = 900  # Auto-Snapshot höchstens alle 15 Min
SNAP_MAX = 50  # Verlaufstiefe pro Doc
INVITE_SECONDS = 7 * 86400  # Einladungs-Links laufen nach 7 Tagen ab
EXPORT_MAX = 100 * 1024 * 1024  # Export-ZIP deckelt bei 100 MB
RATE_SCOPES = {"login": (10, 60), "register": (20, 3600), "join": (30, 60),  # login/register: Defaults, config gewinnt
               "search": (60, 60), "files": (20, 60), "save": (30, 60), "comments": (30, 60),
               "export": (5, 60), "pw": (10, 60)}  # save/comments/export: Spam-Deckel, pw: Passwort-Raten

ROOT = Path(__file__).resolve().parent.parent
try:
    FILES_DIR = config.load().DATA_DIR / "files"
except Exception:
    FILES_DIR = ROOT / "data" / "files"
# run: uvicorn backend.main:app --host 127.0.0.1 --port 8978 --workers 1
ALLOWED_IMG = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".pdf", ".typ", ".bib", ".csv"}
TEXT_SUFFIX = {".typ", ".bib", ".csv"}  # Tabs: als Text editierbar, Rest nur Binär/Shadow

TUTORIAL = """\
#set text(size: 11pt)
#set heading(numbering: "1.")
#set par(justify: true)

#align(center)[
  #text(size: 22pt, weight: "bold")[Willkommen beim Typst Editor]
  \\
  Dein erstes Dokument – leg einfach los!
]

= Schreiben
Einfach tippen. *Fett*, _kursiv_, `Code`, #link("https://typst.app")[Links] und so geht eine Fußnote#footnote[Steht am Seitenende.].

= Listen
- Punkt eins
- Punkt zwei
+ nummeriert mit +
+ statt -

= Mathe
Pythagoras: $a^2 + b^2 = c^2$ und als Block:
$ sum_(k=1)^n k = (n (n+1)) / 2 $

= Tabelle
#table(
  columns: (1fr, 1fr),
  [*Name*], [*Wert*],
  [Zeilen], [Spalten],
)

= Zitat
#quote[Typographie ist die Kunst, Text lesbar zu machen.]

Mehr steht in der #link("https://typst.app/docs")[Typst-Doku] – viel Spaß!
"""

db.init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):  # Shutdown: dirty Rooms sichern (sonst bis 2s Tippen weg)
    yield
    sync.flush_all()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def no_cache_html(req: Request, call):
    if req.url.path.startswith(("/backend", "/data", "/.git", "/tests", "/.github")):
        return JSONResponse({"detail": "Not found"}, status_code=404)  # kein Source/DB-Leak via Static
    res = await call(req)
    if req.url.path == "/" or req.url.path.endswith((".html", ".js")):
        res.headers["Cache-Control"] = "no-store"  # altes Frontend/Bundle darf nie aus Cache leben
    res.headers["X-Content-Type-Options"] = "nosniff"
    res.headers["X-Frame-Options"] = "DENY"
    res.headers["Referrer-Policy"] = "no-referrer"
    res.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' https://cdnjs.cloudflare.com https://esm.sh https://cdn.jsdelivr.net; "
        "connect-src 'self' https://esm.sh https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://packages.typst.org wss: ws:; worker-src 'self' blob:; img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; font-src 'self' data:")
    proto = req.url.scheme
    fwd_proto = (req.headers.get("x-forwarded-proto", "") or "").split(",")[0].strip().lower()
    if proto == "https" or fwd_proto == "https":  # sonst localhost bricken
        res.headers["Strict-Transport-Security"] = "max-age=31536000"
    res.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return res


def me(session: str | None = Cookie(default=None, alias=COOKIE)) -> str:
    user = auth.verify_session(session or "")
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    return user


def need_access(user: str, doc_id: str, allow_trashed: bool = False) -> str:
    r = db.doc_role(user, doc_id)
    if not r:
        raise HTTPException(404, "Doc not found")
    if not allow_trashed and db.is_trashed(doc_id):
        raise HTTPException(410, "Im Papierkorb – erst wiederherstellen")
    return r


def client_ip(req: Request) -> str:
    try:
        if config.load().TRUST_PROXY:
            fwd = req.headers.get("x-forwarded-for", "")
            if fwd.strip():
                return fwd.split(",")[0].strip()
    except Exception:
        pass
    return req.client.host if req.client else "?"


def limited(req: Request, scope: str) -> None:
    # gleiche Antworten, nur seltener: kein Rate-Limit-Orakel als Enumerations-Hilfe
    lim, win = RATE_SCOPES[scope]
    try:
        cfg = config.load()
        if scope == "login":
            lim = cfg.RATE_LOGIN_PER_MIN
        elif scope == "register":
            lim = cfg.RATE_REGISTER_PER_HOUR
    except Exception:
        pass
    if not ratelimit.allow(f"{scope}:{client_ip(req)}", lim, win):
        raise HTTPException(429, "Too many requests")


def user_bytes(user: str) -> int:
    con = db.connect()
    try:
        r = con.execute("SELECT COALESCE(SUM(LENGTH(CAST(content AS BLOB))),0) AS n FROM docs WHERE owner=?", (user,)).fetchone()
        total = int(r["n"] or 0)
        ids = [x["id"] for x in con.execute("SELECT id FROM docs WHERE owner=?", (user,)).fetchall()]
    finally:
        con.close()
    for did in ids:
        d = FILES_DIR / did
        if d.is_dir():
            for p in d.iterdir():
                if p.is_file():
                    try:
                        total += p.stat().st_size
                    except OSError:
                        pass
    return total


def check_quota(user: str, extra: int) -> None:
    try:
        cap = config.load().MAX_BYTES_PER_USER
    except Exception:
        cap = 524288000
    if user_bytes(user) + extra > cap:
        raise HTTPException(413, "Quota voll")


def need_edit(user: str, doc_id: str) -> None:
    if need_access(user, doc_id) not in ("owner", "editor"):
        raise HTTPException(403, "Reviewer darf nur kommentieren")
    if db.is_trashed(doc_id):
        raise HTTPException(410, "Im Papierkorb – erst wiederherstellen")


class Login(BaseModel):
    username: str = Field(max_length=20)
    password: str = Field(max_length=200)  # KDF-Deckel: Riesen-Passwort bremst den Hash nicht aus


class Register(BaseModel):
    username: str = Field(max_length=20)
    password: str = Field(max_length=200)
    invite: str = Field(default="", max_length=200)


class DocCreate(BaseModel):
    title: str = Field(default="Neues Dokument", max_length=100)
    content: str = Field(default="", max_length=200001)  # +1: der 200k-Check im Code antwortet mit 400
    folder: str = Field(default="", max_length=40)  # Ordner in der Sidebar


class DocSave(BaseModel):
    content: str = Field(max_length=200001)


class TitleSet(BaseModel):
    title: str = Field(max_length=100)


class TplSave(BaseModel):
    name: str = Field(max_length=100)
    content: str = Field(default="", max_length=200001)
    folder: str = Field(default="", max_length=40)  # nur bei Neuanlage gesetzt, Update fasst den Ordner nicht an


class Share(BaseModel):
    username: str = Field(max_length=20)
    role: str = Field(default="reviewer", max_length=20)  # editor | reviewer


class CommentNew(BaseModel):
    anchor: int = Field(default=0, ge=0, le=10000000)
    text: str = Field(max_length=2001)  # +1: der 2000-Check im Code antwortet mit 400
    parent_id: str | None = Field(default=None, max_length=100)
    quote: str = Field(default="", max_length=2000)


class AnchorSet(BaseModel):
    anchor: int = Field(ge=0, le=10000000)  # device-pixel Anker: kein Overflow, kein negativ


class CommentEdit(BaseModel):
    text: str = Field(max_length=2001)


class ResolveSet(BaseModel):
    resolved: bool = True


class FolderSet(BaseModel):
    folder: str = Field(default="", max_length=40)


class FolderRename(BaseModel):
    old: str = Field(max_length=40)
    new: str = Field(max_length=40)


class SnapNew(BaseModel):
    label: str = Field(default="", max_length=80)


class FileText(BaseModel):
    content: str = Field(default="", max_length=200001)


class InviteNew(BaseModel):
    role: str = Field(default="reviewer", max_length=20)  # editor | reviewer


class PwChange(BaseModel):
    old: str = Field(max_length=200)
    new: str = Field(max_length=200)


class NameChange(BaseModel):
    name: str = Field(max_length=20)
    password: str = Field(max_length=200)


class PwOnly(BaseModel):
    password: str = Field(max_length=200)


class AvatarSet(BaseModel):
    img: str = Field(default="", max_length=300000)  # data:image/png;base64,... (Frontend skaliert auf 64px)


@app.post("/api/login")
def login(b: Login, res: Response, req: Request):
    limited(req, "login")
    name = b.username.strip()  # wie Register: Leerzeichen außen zählen nicht
    token = auth.create_session(name, b.password)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falscher Login")
    set_cookie(res, req, token)
    return {"user": name, "token": token}  # Token auch im Body: WS-Client braucht es als Query-Param


def set_cookie(res: Response, req: Request, token: str) -> None:
    cfg = config.load()
    if cfg.COOKIE_SECURE == "true":
        secure = True
    elif cfg.COOKIE_SECURE == "false":
        secure = False
    else:
        proto = req.url.scheme
        if cfg.TRUST_PROXY:
            proto = (req.headers.get("x-forwarded-proto", "") or proto).split(",")[0].strip() or proto
        secure = proto == "https"
    res.set_cookie(COOKIE, token, max_age=auth.SESSION_SECONDS, httponly=True,
                   samesite="lax", secure=secure)


@app.post("/api/register")
def register(b: Register, res: Response, req: Request):
    limited(req, "register")
    cfg = config.load()
    if cfg.REGISTRATION not in ("open", "invite-only", "closed"):
        raise HTTPException(403, "Registration disabled")  # fail closed bei Tippfehlern
    if cfg.REGISTRATION == "closed":
        raise HTTPException(403, "Registration disabled")
    if cfg.REGISTRATION == "invite-only" and (not cfg.REGISTRATION_INVITE_TOKEN or b.invite != cfg.REGISTRATION_INVITE_TOKEN):
        raise HTTPException(403, "Invalid invite")
    name = b.username.strip()
    if not re.fullmatch(NAME_RE, name):
        raise HTTPException(400, "Name: 2-20 Zeichen, Buchstaben/Zahlen/_-")
    if not MIN_PW <= len(b.password) <= MAX_PW:
        raise HTTPException(400, "Passwort: 8-200 Zeichen")
    con = db.connect()
    try:
        if con.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone():
            raise HTTPException(400, "Name vergeben")
        con.execute("INSERT INTO users (name, hash) VALUES (?,?)", (name, auth.hash_password(b.password)))
        did, now = db.new_id("d_"), db.now_iso()  # jeder neue Account startet mit Tutorial
        con.execute("INSERT INTO docs (id, owner, title, content, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                    (did, name, "Tutorial", TUTORIAL, now, now))
        con.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Name vergeben")
    finally:
        con.close()
    token = auth.mint(name)
    set_cookie(res, req, token)
    return {"user": name, "token": token}


@app.post("/api/logout")
def logout(req: Request, res: Response):
    if req.cookies.get(COOKIE):
        auth.delete_session(req.cookies[COOKIE])
    res.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def get_me(user: str = Depends(me)):
    con = db.connect()
    try:
        r = con.execute("SELECT avatar FROM users WHERE name=?", (user,)).fetchone()
        return {"user": user, "hasAvatar": bool(r and r["avatar"])}
    finally:
        con.close()


def check_pw(user: str, password: str) -> None:
    con = db.connect()
    try:
        row = con.execute("SELECT hash FROM users WHERE name=?", (user,)).fetchone()
        if not row or not auth.check_password(password, row["hash"]):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falsches Passwort")
    finally:
        con.close()


@app.post("/api/me/password")
async def change_password(b: PwChange, req: Request, user: str = Depends(me)):
    limited(req, "pw")  # altes Passwort raten ist sonst frei
    check_pw(user, b.old)
    if not MIN_PW <= len(b.new) <= MAX_PW:
        raise HTTPException(400, "Passwort: 8-200 Zeichen")
    con = db.connect()
    try:
        con.execute("UPDATE users SET hash=? WHERE name=?", (auth.hash_password(b.new), user))
        cur = auth.sha(req.cookies.get(COOKIE, ""))
        con.execute("DELETE FROM sessions WHERE username=? AND token_hash!=?", (user, cur))
        con.commit()
    finally:
        con.close()
    await sync.kick_all(user)  # offene Sockets zu: alte Session tippt nicht weiter
    return {"ok": True}


@app.post("/api/me/name")
def rename_me(b: NameChange, req: Request, user: str = Depends(me)):
    limited(req, "pw")  # s. change_password
    new = b.name.strip()
    if not re.fullmatch(NAME_RE, new):
        raise HTTPException(400, "Name: 2-20 Zeichen, Buchstaben/Zahlen/_-")
    check_pw(user, b.password)
    con = db.connect()
    try:
        if new != user and con.execute("SELECT 1 FROM users WHERE name=?", (new,)).fetchone():
            raise HTTPException(400, "Name vergeben")
        if new == user:
            return {"user": user}
        row = con.execute("SELECT hash, avatar FROM users WHERE name=?", (user,)).fetchone()
        if not row:
            raise HTTPException(404, "User weg")
        try:
            con.execute("INSERT INTO users (name, hash, avatar) VALUES (?,?,?)",  # erst neuer Parent ...
                        (new, row["hash"], row["avatar"]))
            con.execute("UPDATE sessions SET username=? WHERE username=?", (new, user))
            con.execute("UPDATE docs SET owner=? WHERE owner=?", (new, user))
            con.execute("UPDATE shares SET username=? WHERE username=?", (new, user))
            con.execute("UPDATE comments SET username=? WHERE username=?", (new, user))  # sonst Waisen (Autor-Check)
            con.execute("UPDATE templates SET owner=? WHERE owner=?", (new, user))
            con.execute("UPDATE folders SET owner=? WHERE owner=?", (new, user))  # sonst sind leere Ordner weg
            con.execute("DELETE FROM users WHERE name=?", (user,))  # ... dann alter weg (nichts hängt mehr dran)
            con.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(400, "Umbenennen fehlgeschlagen")
        return {"user": new}
    finally:
        con.close()


@app.post("/api/me/avatar")
def set_avatar(b: AvatarSet, user: str = Depends(me)):
    m = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", b.img)
    if not m or len(b.img) > 200_000:
        raise HTTPException(400, "Nur PNG/JPEG/WebP als Data-URL (max 200 KB)")
    con = db.connect()
    try:
        con.execute("UPDATE users SET avatar=? WHERE name=?", (m.group(1) + ":" + m.group(2), user))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.delete("/api/me/avatar")
def del_avatar(user: str = Depends(me)):
    con = db.connect()
    try:
        con.execute("UPDATE users SET avatar='' WHERE name=?", (user,))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.get("/api/avatar/{username}")
def get_avatar(username: str, user: str = Depends(me)):
    con = db.connect()
    try:
        r = con.execute("SELECT avatar FROM users WHERE name=?", (username,)).fetchone()
        if not r or not r["avatar"]:
            raise HTTPException(404, "Kein Bild")
        val = r["avatar"]
        if ":" in val:
            kind, b64 = val.split(":", 1)
            mime = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}.get(kind, "image/png")
        else:
            b64, mime = val, "image/png"
        try:
            raw = base64.b64decode(b64)
        except Exception:
            raise HTTPException(404, "Kein Bild")
        return Response(content=raw, media_type=mime,
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    finally:
        con.close()


@app.post("/api/me/delete")
async def delete_me(b: PwOnly, req: Request, res: Response, user: str = Depends(me)):
    limited(req, "pw")  # s. change_password
    check_pw(user, b.password)
    con = db.connect()
    try:
        owned = [r["id"] for r in con.execute("SELECT id FROM docs WHERE owner=?", (user,)).fetchall()]
        con.execute("DELETE FROM comments WHERE username=? AND parent_id IS NOT NULL", (user,))  # eigene Antworten weg
        con.execute("UPDATE comments SET username='[gelöscht]' WHERE username=?", (user,))  # eigene Threads bleiben (fremde Antworten auch)
        con.execute("DELETE FROM users WHERE name=?", (user,))  # docs/shares/sessions via CASCADE
        con.commit()
    finally:
        con.close()
    for did in owned:
        await sync.drop(did)  # RAM-Room weg + Sockets zu, sonst tippt wer im Geist weiter
        shutil.rmtree(FILES_DIR / did, ignore_errors=True)
    if req.cookies.get(COOKIE):
        auth.delete_session(req.cookies[COOKIE])
    res.delete_cookie(COOKIE)
    return {"ok": True}


# Live-Sync (Yjs-Protokoll): ein Prozess, kein Node mehr.
@app.websocket("/ws/{doc_id}")
async def ws_doc(ws: WebSocket, doc_id: str):
    await sync.handle(ws, doc_id)


@app.get("/api/docs")
def list_docs(user: str = Depends(me)):
    con = db.connect()
    try:
        own = con.execute("SELECT id, title, folder, updated_at FROM docs WHERE owner=? AND trashed=0 "
                          "ORDER BY updated_at DESC", (user,)).fetchall()
        shared = con.execute(
            "SELECT d.id, d.title, d.owner, d.updated_at, s.role FROM docs d JOIN shares s ON s.doc_id=d.id "
            "WHERE s.username=? AND d.trashed=0 ORDER BY d.updated_at DESC", (user,)).fetchall()
        trash = con.execute("SELECT id, title, updated_at FROM docs WHERE owner=? AND trashed=1 "
                            "ORDER BY updated_at DESC", (user,)).fetchall()
        return {"own": [dict(r) for r in own],
                "shared": [dict(r) for r in shared],
                "trash": [dict(r) for r in trash]}
    finally:
        con.close()


@app.get("/api/folders")
def list_folders(user: str = Depends(me)):
    con = db.connect()
    try:  # explizite (auch leere) + benutzte Ordner vereint, Zähler aus den Docs
        rows = con.execute("SELECT folder, COUNT(*) AS n FROM docs WHERE owner=? AND trashed=0 AND folder<>'' "
                           "GROUP BY folder ORDER BY folder", (user,)).fetchall()
        counts = {r["folder"]: r["n"] for r in rows}
        for r in con.execute("SELECT name FROM folders WHERE owner=? AND kind='doc' ORDER BY name", (user,)).fetchall():
            counts.setdefault(r["name"], 0)
        return {"folders": [{"folder": f, "n": counts[f]} for f in sorted(counts)]}
    finally:
        con.close()


def ensure_folder(con, user: str, kind: str, name: str) -> None:
    n = name.strip()[:FOLDER_MAX]
    if n:
        con.execute("INSERT OR IGNORE INTO folders (owner, kind, name, created_at) VALUES (?,?,?,?)",
                    (user, kind, n, db.now_iso()))


def check_folder_name(name: str) -> str:
    n = name.strip()[:FOLDER_MAX]
    if not n:
        raise HTTPException(400, "Leerer Ordnername")
    return n


@app.post("/api/folders")
def make_folder(b: FolderSet, user: str = Depends(me)):
    n = check_folder_name(b.folder)
    con = db.connect()
    try:
        ensure_folder(con, user, "doc", n)
        con.commit()
        return {"folder": n}
    finally:
        con.close()


@app.post("/api/docs/create")
def create_doc(b: DocCreate, user: str = Depends(me)):
    t = b.title.strip()
    if not t or len(t) > TITLE_MAX:
        raise HTTPException(400, f"Titel: 1-{TITLE_MAX} Zeichen")
    if len(b.content) > MAX_TXT:
        raise HTTPException(400, "Doc zu groß (max 200 KB)")
    check_quota(user, len(b.content))
    did, now = db.new_id("d_"), db.now_iso()
    con = db.connect()
    try:
        try:
            max_docs = config.load().MAX_DOCS_PER_USER
        except Exception:
            max_docs = 100
        if con.execute("SELECT COUNT(*) AS n FROM docs WHERE owner=?", (user,)).fetchone()["n"] >= max_docs:
            raise HTTPException(400, "Zu viele Docs")
        con.execute("INSERT INTO docs (id, owner, title, content, folder, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (did, user, t, b.content,
                     b.folder.strip()[:FOLDER_MAX], now, now))
        ensure_folder(con, user, "doc", b.folder)
        con.commit()
        return {"id": did}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Titel gibt es schon")
    finally:
        con.close()


@app.get("/api/docs/{doc_id}")
def get_doc(doc_id: str, user: str = Depends(me)):
    r = need_access(user, doc_id)
    con = db.connect()
    try:
        d = con.execute("SELECT id, owner, title, content, folder, trashed, updated_at FROM docs WHERE id=?",
                        (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, "Doc weg")
        users = con.execute("SELECT username, role FROM shares WHERE doc_id=?", (doc_id,)).fetchall()
        return {**dict(d), "role": r, "shares": [dict(u) for u in users]}
    finally:
        con.close()


def prune_snaps(con: sqlite3.Connection, doc_id: str) -> None:
    con.execute("DELETE FROM snapshots WHERE doc_id=? AND id NOT IN "
                "(SELECT id FROM snapshots WHERE doc_id=? ORDER BY created_at DESC LIMIT ?)",
                (doc_id, doc_id, SNAP_MAX))


def auto_snap(doc_id: str, content: str, label: str = "") -> None:
    """Verlauf: höchstens alle SNAP_EVERY ein Stand, älteste über SNAP_MAX weg."""
    con = db.connect()
    try:
        last = con.execute("SELECT created_at FROM snapshots WHERE doc_id=? ORDER BY created_at DESC LIMIT 1",
                           (doc_id,)).fetchone()
        cut = (datetime.now(timezone.utc) - timedelta(seconds=SNAP_EVERY)).isoformat()
        if label or not last or last["created_at"] < cut:
            con.execute("INSERT INTO snapshots (id, doc_id, content, label, created_at) VALUES (?,?,?,?,?)",
                        (db.new_id("s_"), doc_id, content, label, db.now_iso()))
            prune_snaps(con, doc_id)
            con.commit()
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/save")
def save_doc(doc_id: str, b: DocSave, req: Request, user: str = Depends(me)):
    limited(req, "save")  # Save-Spam deckeln
    need_edit(user, doc_id)
    live = sync.room_text(doc_id)  # Room ist neuer als der einzelne Save ("" ist gültig, nur None heißt kein Room)
    content = live if live is not None else b.content
    if len(content) > MAX_TXT:
        raise HTTPException(400, "Doc zu groß (max 200 KB)")
    check_quota(user, len(content))
    con = db.connect()
    try:
        con.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?",
                    (content, db.now_iso(), doc_id))
        con.commit()
    finally:
        con.close()
    if not sync.persist(doc_id):
        db.clear_room_state(doc_id)  # kein Room: Bytes wären stale, neu aus content bauen
    auto_snap(doc_id, content)
    return {"ok": True}


@app.post("/api/docs/{doc_id}/rename")
def rename_doc(doc_id: str, b: TitleSet, user: str = Depends(me)):
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Nur Owner kann umbenennen")
    t = b.title.strip()
    if not t or len(t) > TITLE_MAX:
        raise HTTPException(400, f"Titel: 1-{TITLE_MAX} Zeichen")
    con = db.connect()
    try:
        con.execute("UPDATE docs SET title=?, updated_at=? WHERE id=?", (t, db.now_iso(), doc_id))
        con.commit()
        return {"ok": True}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Titel gibt es schon")
    finally:
        con.close()


@app.get("/api/templates")
def list_templates(user: str = Depends(me)):
    con = db.connect()
    try:
        rows = con.execute("SELECT name, content, line, folder FROM templates WHERE owner=? ORDER BY name",
                           (user,)).fetchall()
        return {"templates": [dict(r) for r in rows]}
    finally:
        con.close()


@app.post("/api/templates")
def save_template(b: TplSave, user: str = Depends(me)):
    n = re.sub(r"[^A-Za-z0-9._-]", "_", Path(b.name or "").name.strip().lstrip("."))[:100]
    if not n.endswith(".typ") or not b.content.strip() or len(b.content) > MAX_TXT:
        raise HTTPException(400, "Nur .typ mit Inhalt (max 200 KB)")
    check_quota(user, len(b.content))
    con = db.connect()
    try:
        con.execute("INSERT INTO templates (owner, name, content, line, folder, updated_at) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT (owner, name) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at",
                    (user, n, b.content, f'#include "{n}"', b.folder.strip()[:FOLDER_MAX], db.now_iso()))
        ensure_folder(con, user, "tpl", b.folder)
        con.commit()
        return {"name": n}
    finally:
        con.close()


@app.delete("/api/templates/{name}")
def delete_template(name: str, user: str = Depends(me)):
    con = db.connect()
    try:
        con.execute("DELETE FROM templates WHERE owner=? AND name=?", (user, name))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/templates/{name}/folder")
def move_template(name: str, b: FolderSet, user: str = Depends(me)):
    con = db.connect()
    try:
        con.execute("UPDATE templates SET folder=?, updated_at=? WHERE owner=? AND name=?",
                    (b.folder.strip()[:FOLDER_MAX], db.now_iso(), user, name))
        ensure_folder(con, user, "tpl", b.folder)
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.get("/api/tplfolders")
def list_tpl_folders(user: str = Depends(me)):
    con = db.connect()
    try:
        rows = con.execute("SELECT folder, COUNT(*) AS n FROM templates WHERE owner=? AND folder<>'' "
                           "GROUP BY folder ORDER BY folder", (user,)).fetchall()
        counts = {r["folder"]: r["n"] for r in rows}
        for r in con.execute("SELECT name FROM folders WHERE owner=? AND kind='tpl' ORDER BY name", (user,)).fetchall():
            counts.setdefault(r["name"], 0)
        return {"folders": [{"folder": f, "n": counts[f]} for f in sorted(counts)]}
    finally:
        con.close()


@app.post("/api/tplfolders")
def make_tpl_folder(b: FolderSet, user: str = Depends(me)):
    n = check_folder_name(b.folder)
    con = db.connect()
    try:
        ensure_folder(con, user, "tpl", n)
        con.commit()
        return {"folder": n}
    finally:
        con.close()


@app.post("/api/tplfolders/rename")
def rename_tpl_folder(b: FolderRename, user: str = Depends(me)):
    old, new = b.old.strip()[:FOLDER_MAX], b.new.strip()[:FOLDER_MAX]
    if not old or not new or old == new:
        raise HTTPException(400, "Leerer Ordnername")
    con = db.connect()
    try:
        con.execute("UPDATE templates SET folder=?, updated_at=? WHERE owner=? AND folder=?",
                    (new, db.now_iso(), user, old))
        con.execute("UPDATE OR IGNORE folders SET name=? WHERE owner=? AND kind='tpl' AND name=?",
                    (new, user, old))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.delete("/api/tplfolders/{name}")
def drop_tpl_folder(name: str, user: str = Depends(me)):
    n = name.strip()[:FOLDER_MAX]
    con = db.connect()
    try:
        con.execute("UPDATE templates SET folder='' WHERE owner=? AND folder=?", (user, n))
        con.execute("DELETE FROM folders WHERE owner=? AND kind='tpl' AND name=?", (user, n))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.delete("/api/docs/{doc_id}")
async def delete_doc(doc_id: str, user: str = Depends(me)):
    r = need_access(user, doc_id, allow_trashed=True)
    if r != "owner":
        raise HTTPException(403, "Nur Owner kann löschen")
    con = db.connect()
    try:
        row = con.execute("SELECT trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Doc weg")
        trashed = row["trashed"]
        if not trashed:  # 1. Löschen = Papierkorb, 2. = endgültig
            con.execute("UPDATE docs SET trashed=1, updated_at=? WHERE id=?", (db.now_iso(), doc_id))
            con.commit()
            await sync.drop(doc_id)  # Room zu + Sockets zu: kein Geist-Tippen nach Trash
            return {"trashed": True}
        con.execute("DELETE FROM docs WHERE id=?", (doc_id,))
        con.commit()
    finally:
        con.close()
    await sync.drop(doc_id)  # RAM-Room weg (s. delete_me)
    shutil.rmtree(FILES_DIR / doc_id, ignore_errors=True)  # Dateien weg (Fix #3)
    return {"trashed": False}


@app.post("/api/docs/{doc_id}/restore")
def restore_doc(doc_id: str, user: str = Depends(me)):
    if need_access(user, doc_id, allow_trashed=True) != "owner":
        raise HTTPException(403, "Nur Owner kann wiederherstellen")
    con = db.connect()
    try:
        con.execute("UPDATE docs SET trashed=0, updated_at=? WHERE id=?", (db.now_iso(), doc_id))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/folder")
def move_doc(doc_id: str, b: FolderSet, user: str = Depends(me)):
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Nur Owner sortiert")  # Ordner lebt in der Owner-Sidebar
    con = db.connect()
    try:
        con.execute("UPDATE docs SET folder=?, updated_at=? WHERE id=?",
                    (b.folder.strip()[:FOLDER_MAX], db.now_iso(), doc_id))
        ensure_folder(con, user, "doc", b.folder)
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.delete("/api/folders/{name}")
def drop_folder(name: str, user: str = Depends(me)):
    n = name.strip()[:FOLDER_MAX]
    con = db.connect()
    try:  # Ordner weg: Docs bleiben, liegen danach oben
        con.execute("UPDATE docs SET folder='' WHERE owner=? AND folder=? AND trashed=0", (user, n))
        con.execute("DELETE FROM folders WHERE owner=? AND kind='doc' AND name=?", (user, n))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/folders/rename")
def rename_folder(b: FolderRename, user: str = Depends(me)):
    old, new = b.old.strip()[:FOLDER_MAX], b.new.strip()[:FOLDER_MAX]
    if not old or not new or old == new:
        raise HTTPException(400, "Leerer Ordnername")
    con = db.connect()
    try:  # ein Update: kein halb umbenannter Ordner bei Teilfehlern
        con.execute("UPDATE docs SET folder=?, updated_at=? WHERE owner=? AND folder=? AND trashed=0",
                    (new, db.now_iso(), user, old))
        con.execute("UPDATE OR IGNORE folders SET name=? WHERE owner=? AND kind='doc' AND name=?",
                    (new, user, old))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/duplicate")
def duplicate_doc(doc_id: str, user: str = Depends(me)):
    need_edit(user, doc_id)  # lesen reicht nicht: reviewer darf schauen, aber nicht kopieren
    try:
        max_docs = config.load().MAX_DOCS_PER_USER
    except Exception:
        max_docs = 100
    con = db.connect()
    try:
        if con.execute("SELECT COUNT(*) AS n FROM docs WHERE owner=?", (user,)).fetchone()["n"] >= max_docs:
            raise HTTPException(400, "Zu viele Docs")
        d = con.execute("SELECT title, content, folder FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, "Doc weg")
        base = d["title"] + " (Kopie)"
        title, i = base, 2
        while con.execute("SELECT 1 FROM docs WHERE owner=? AND title=? COLLATE NOCASE",
                          (user, title)).fetchone():
            title, i = f"{base} {i}", i + 1
            if i > 99:
                raise HTTPException(400, "Zu viele Kopien")
        nid, now = db.new_id("d_"), db.now_iso()
        live = sync.room_text(doc_id)  # bis 2s Tippen steckt nur im Room, nicht in der DB
        text = live if live is not None else d["content"]
        check_quota(user, len(text))
        try:
            con.execute("INSERT INTO docs (id, owner, title, content, folder, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (nid, user, title, text, d["folder"], now, now))
            con.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(400, "Titel gibt es schon")
    finally:
        con.close()
    src = FILES_DIR / doc_id
    if src.is_dir():  # Dateien mitnehmen (Bilder/Tabs), Fehler ignorieren
        shutil.copytree(src, FILES_DIR / nid, ignore=shutil.ignore_patterns(".*"), dirs_exist_ok=True)
    return {"id": nid}


@app.post("/api/docs/{doc_id}/share")
def share_doc(doc_id: str, b: Share, user: str = Depends(me)):
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Nur Owner kann einladen")
    if b.role not in ("editor", "reviewer"):
        raise HTTPException(400, "role muss editor oder reviewer sein")
    con = db.connect()
    try:
        if not con.execute("SELECT 1 FROM users WHERE name=?", (b.username,)).fetchone():
            raise HTTPException(404, "User gibt es nicht")
        prev = con.execute("SELECT role FROM shares WHERE doc_id=? AND username=?",
                           (doc_id, b.username)).fetchone()
        con.execute("INSERT INTO shares (doc_id, username, role) VALUES (?,?,?) "
                    "ON CONFLICT (doc_id, username) DO UPDATE SET role=excluded.role",
                    (doc_id, b.username, b.role))
        if b.role == "reviewer" and prev and prev["role"] == "editor":
            con.execute("DELETE FROM invites WHERE doc_id=? AND role='editor'",  # offene Editor-Links sterben mit
                        (doc_id,))  # dem Downgrade, sonst lädt der Link die Rechte wieder hoch
            r = sync.rooms.get(doc_id)
            if r:  # Rollen-Cache weg: Downgrade wirkt sofort statt erst nach 10s
                r.get("role_cache", {}).pop(b.username, None)
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.delete("/api/docs/{doc_id}/share/{username}")
async def unshare_doc(doc_id: str, username: str, user: str = Depends(me)):
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Nur Owner kann entfernen")
    con = db.connect()
    try:
        con.execute("DELETE FROM shares WHERE doc_id=? AND username=?", (doc_id, username))
        con.execute("DELETE FROM invites WHERE doc_id=?", (doc_id,))  # raus ist raus: alte Links sterben mit
        con.commit()
    finally:
        con.close()
    await sync.kick_user(doc_id, username)
    return {"ok": True}


@app.get("/api/docs/{doc_id}/comments")
def list_comments(doc_id: str, user: str = Depends(me)):
    need_access(user, doc_id)
    con = db.connect()
    try:
        rows = con.execute("SELECT id, username, anchor, quote, text, parent_id, resolved, created_at FROM comments "
                           "WHERE doc_id=? ORDER BY created_at", (doc_id,)).fetchall()
        tops = [dict(r) for r in rows if not r["parent_id"]]
        reps: dict[str, list] = {}
        for r in rows:
            if r["parent_id"]:
                reps.setdefault(r["parent_id"], []).append(dict(r))
        for t in tops:
            t["replies"] = reps.get(t["id"], [])
        return {"comments": tops}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/comments")
def add_comment(doc_id: str, b: CommentNew, req: Request, user: str = Depends(me)):
    limited(req, "comments")  # Kommentar-Spam deckeln
    need_access(user, doc_id)  # jede Rolle darf kommentieren
    if not b.text.strip() or len(b.text) > 2000:
        raise HTTPException(400, "Kommentar: 1-2000 Zeichen")
    if b.anchor < 0:
        raise HTTPException(400, "Anker < 0")
    cid = db.new_id("c_")
    con = db.connect()
    try:
        if b.parent_id:  # Antwort nur auf Top-Threads im selben Doc
            p = con.execute("SELECT parent_id FROM comments WHERE id=? AND doc_id=?",
                            (b.parent_id, doc_id)).fetchone()
            if not p:
                raise HTTPException(404, "Thread weg")
            if p["parent_id"]:
                raise HTTPException(400, "Antwort auf Antwort geht nicht")
        con.execute("INSERT INTO comments (id, doc_id, username, anchor, quote, text, parent_id, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (cid, doc_id, user, b.anchor, b.quote.strip()[:500], b.text.strip(), b.parent_id, db.now_iso()))
        con.commit()
        return {"id": cid}
    finally:
        con.close()


@app.delete("/api/docs/{doc_id}/comments/{cid}")
def delete_comment(doc_id: str, cid: str, user: str = Depends(me)):
    role = need_access(user, doc_id)
    con = db.connect()
    try:
        t = con.execute("SELECT username, parent_id FROM comments WHERE id=? AND doc_id=?",
                        (cid, doc_id)).fetchone()
        if not t:
            raise HTTPException(404, "Kommentar weg")
        if role != "owner" and t["username"] != user:
            raise HTTPException(403, "Nur Autor oder Owner")
        if t["parent_id"]:  # Antwort: nur die eine Zeile weg
            con.execute("DELETE FROM comments WHERE id=?", (cid,))
        else:
            con.execute("DELETE FROM comments WHERE id=? OR parent_id=?", (cid, cid))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/comments/{cid}/anchor")
def move_comment(doc_id: str, cid: str, b: AnchorSet, user: str = Depends(me)):
    need_access(user, doc_id)  # wandert mit dem Text mit
    if b.anchor < 0:
        raise HTTPException(400, "Anker < 0")
    con = db.connect()
    try:
        r = con.execute("SELECT username FROM comments WHERE id=? AND doc_id=? AND parent_id IS NULL",
                        (cid, doc_id)).fetchone()
        if not r:
            raise HTTPException(404, "Kommentar weg")
        if r["username"] != user:
            raise HTTPException(403, "Nur Autor")
        con.execute("UPDATE comments SET anchor=? WHERE id=?", (b.anchor, cid))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/comments/{cid}/edit")
def edit_comment(doc_id: str, cid: str, b: CommentEdit, user: str = Depends(me)):
    need_access(user, doc_id)  # nur der Autor ändert (Owner löscht statt zu ändern)
    if not b.text.strip() or len(b.text.strip()) > 2000:
        raise HTTPException(400, "Kommentar: 1-2000 Zeichen")
    con = db.connect()
    try:
        r = con.execute("SELECT username FROM comments WHERE id=? AND doc_id=?",
                        (cid, doc_id)).fetchone()
        if not r:
            raise HTTPException(404, "Kommentar weg")
        if r["username"] != user:
            raise HTTPException(403, "Nur Autor")
        con.execute("UPDATE comments SET text=? WHERE id=?", (b.text.strip(), cid))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/comments/{cid}/resolve")
def resolve_comment(doc_id: str, cid: str, b: ResolveSet, user: str = Depends(me)):
    role = need_access(user, doc_id)  # Autor oder Owner hakt ab
    con = db.connect()
    try:
        r = con.execute("SELECT username, parent_id FROM comments WHERE id=? AND doc_id=?",
                        (cid, doc_id)).fetchone()
        if not r:
            raise HTTPException(404, "Kommentar weg")
        top = cid if not r["parent_id"] else r["parent_id"]
        a = con.execute("SELECT username FROM comments WHERE id=?", (top,)).fetchone()
        if role != "owner" and (not a or a["username"] != user):
            raise HTTPException(403, "Nur Autor oder Owner")
        con.execute("UPDATE comments SET resolved=? WHERE id=?", (1 if b.resolved else 0, top))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


def safe_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name or "").name.strip().lstrip("."))[:100]
    if not n or Path(n).suffix.lower() not in ALLOWED_IMG:
        raise HTTPException(400, "Nur png/jpg/jpeg/svg/gif/webp/pdf/typ/bib/csv")
    return n


@app.get("/api/docs/{doc_id}/files")
def list_files(doc_id: str, user: str = Depends(me)):
    need_access(user, doc_id)
    d = FILES_DIR / doc_id
    out = []
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if p.is_file():
                st = p.stat()
                out.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime})
    return {"files": out}


@app.post("/api/docs/{doc_id}/files")
def upload_file(doc_id: str, f: UploadFile, req: Request, user: str = Depends(me)):
    limited(req, "files")
    need_edit(user, doc_id)
    n = safe_name(f.filename or "")
    try:
        max_files = config.load().MAX_FILES_PER_DOC
    except Exception:
        max_files = 200
    d = FILES_DIR / doc_id
    d.mkdir(parents=True, exist_ok=True)
    if sum(1 for p in d.iterdir() if p.is_file() and p.name != n) >= max_files:
        raise HTTPException(400, "Zu viele Dateien")
    size, chunks = 0, []
    while True:
        blk = f.file.read(64 * 1024)
        if not blk:
            break
        size += len(blk)
        if size > 10 * 1024 * 1024:
            raise HTTPException(400, "Max 10 MB")
        chunks.append(blk)
    check_quota(user, size)
    (d / n).write_bytes(b"".join(chunks))
    touch_doc(doc_id)
    return {"name": n, "size": size}


@app.get("/api/docs/{doc_id}/files/{name}")
def get_file(doc_id: str, name: str, user: str = Depends(me)):
    need_access(user, doc_id)
    p = FILES_DIR / doc_id / safe_name(name)
    if not p.is_file():
        raise HTTPException(404, "Datei weg")
    if p.suffix.lower() == ".svg":  # SVG inline = Skript im Seiten-Kontext (Fix #8)
        return Response(content=p.read_bytes(), media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{p.name}"'})
    return FileResponse(str(p))


@app.delete("/api/docs/{doc_id}/files/{name}")
def delete_file(doc_id: str, name: str, user: str = Depends(me)):
    need_edit(user, doc_id)
    p = FILES_DIR / doc_id / safe_name(name)
    if p.is_file():
        p.unlink()
    touch_doc(doc_id)
    return {"ok": True}


def need_text(name: str) -> str:
    n = safe_name(name)
    if Path(n).suffix.lower() not in TEXT_SUFFIX:
        raise HTTPException(400, "Nur typ/bib/csv als Text")
    return n


def touch_doc(doc_id: str) -> None:  # Datei-Änderung: Sidebar-Sortierung bleibt frisch
    con = db.connect()
    try:
        con.execute("UPDATE docs SET updated_at=? WHERE id=?", (db.now_iso(), doc_id))
        con.commit()
    finally:
        con.close()


@app.get("/api/docs/{doc_id}/files/{name}/text")
def get_file_text(doc_id: str, name: str, user: str = Depends(me)):
    need_access(user, doc_id)
    p = FILES_DIR / doc_id / need_text(name)
    if not p.is_file():
        raise HTTPException(404, "Datei weg")
    return {"name": p.name, "content": p.read_text(encoding="utf-8", errors="replace")}


@app.post("/api/docs/{doc_id}/files/{name}/text")
def save_file_text(doc_id: str, name: str, b: FileText, user: str = Depends(me)):
    need_edit(user, doc_id)
    if len(b.content) > MAX_TXT:
        raise HTTPException(400, "Max 200 KB")
    check_quota(user, len(b.content))
    p = FILES_DIR / doc_id / need_text(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(b.content, encoding="utf-8")
    touch_doc(doc_id)
    return {"ok": True}


@app.post("/api/docs/{doc_id}/invite")
def make_invite(doc_id: str, b: InviteNew, user: str = Depends(me)):
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Nur Owner kann einladen")
    if b.role not in ("editor", "reviewer"):
        raise HTTPException(400, "role muss editor oder reviewer sein")
    tok = db.new_id("")
    con = db.connect()
    try:
        con.execute("INSERT INTO invites (token, doc_id, role, hint, created_at) VALUES (?,?,?,?,?)",
                    (auth.sha(tok), doc_id, b.role, tok[:8], db.now_iso()))  # nur der Hash liegt in der DB
        con.commit()
        return {"token": tok}
    finally:
        con.close()


@app.get("/api/docs/{doc_id}/invites")
def list_invites(doc_id: str, user: str = Depends(me)):
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Nur Owner")
    con = db.connect()
    try:
        rows = con.execute("SELECT hint, role, created_at FROM invites WHERE doc_id=? ORDER BY created_at",
                           (doc_id,)).fetchall()
        return {"invites": [dict(r) for r in rows]}
    finally:
        con.close()


@app.delete("/api/docs/{doc_id}/invites/{hint}")
def drop_invite(doc_id: str, hint: str, user: str = Depends(me)):
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Nur Owner")
    con = db.connect()
    try:  # per hint: löscht alle Treffer im Doc (8 Zeichen können kollidieren, Risiko vernachlässigbar)
        con.execute("DELETE FROM invites WHERE doc_id=? AND hint=?", (doc_id, hint))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/join/{token}")
def join_doc(token: str, req: Request, user: str = Depends(me)):
    limited(req, "join")
    con = db.connect()
    try:
        inv = con.execute("SELECT doc_id, role, created_at FROM invites WHERE token=?",
                          (auth.sha(token),)).fetchone()
        if not inv:  # alte DB: Klartext-Token einmalig auf Hash heben
            inv = con.execute("SELECT doc_id, role, created_at FROM invites WHERE token=?",
                              (token,)).fetchone()
            if inv:
                try:
                    con.execute("UPDATE invites SET token=? WHERE token=?", (auth.sha(token), token))
                    con.commit()
                except Exception:
                    pass
        if not inv:
            raise HTTPException(404, "Einladung ungültig")
        cut = (datetime.now(timezone.utc) - timedelta(seconds=INVITE_SECONDS)).isoformat()
        if (inv["created_at"] or "") < cut:
            con.execute("DELETE FROM invites WHERE token=? OR token=?",  # Hash + Klartext: Legacy-Leichen weg
                        (auth.sha(token), token))
            con.commit()
            raise HTTPException(404, "Einladung ungültig")
        d = con.execute("SELECT owner, trashed FROM docs WHERE id=?", (inv["doc_id"],)).fetchone()
        if not d:
            raise HTTPException(404, "Doc weg")
        if d["trashed"]:
            raise HTTPException(410, "Im Papierkorb – erst wiederherstellen")
        if d["owner"] != user:
            con.execute("INSERT INTO shares (doc_id, username, role) VALUES (?,?,?) "
                        "ON CONFLICT (doc_id, username) DO NOTHING",  # Link gibt Zugang, aber kein Upgrade
                        (inv["doc_id"], user, inv["role"]))
            con.commit()
        return {"id": inv["doc_id"]}
    finally:
        con.close()


@app.get("/api/docs/{doc_id}/snapshots")
def list_snaps(doc_id: str, user: str = Depends(me)):
    need_access(user, doc_id)
    con = db.connect()
    try:
        rows = con.execute("SELECT id, label, created_at, LENGTH(content) AS size FROM snapshots "
                           "WHERE doc_id=? ORDER BY created_at DESC", (doc_id,)).fetchall()
        return {"snapshots": [dict(r) for r in rows]}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/snapshots")
def make_snap(doc_id: str, b: SnapNew, user: str = Depends(me)):
    need_edit(user, doc_id)
    live = sync.room_text(doc_id)  # manueller Stand: Room ist neuer als DB
    con = db.connect()
    try:
        row = con.execute("SELECT content FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Doc weg")
        cur = live if live is not None else row["content"]
        sid = db.new_id("s_")
        con.execute("INSERT INTO snapshots (id, doc_id, content, label, created_at) VALUES (?,?,?,?,?)",
                    (sid, doc_id, cur, b.label.strip()[:80], db.now_iso()))
        prune_snaps(con, doc_id)
        con.commit()
        return {"id": sid}
    finally:
        con.close()


@app.get("/api/docs/{doc_id}/snapshots/{sid}")
def get_snap(doc_id: str, sid: str, user: str = Depends(me)):
    need_access(user, doc_id)  # Inhalt für Diff-Ansicht
    con = db.connect()
    try:
        r = con.execute("SELECT content, label, created_at FROM snapshots WHERE id=? AND doc_id=?",
                        (sid, doc_id)).fetchone()
        if not r:
            raise HTTPException(404, "Stand weg")
        return dict(r)
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/snapshots/{sid}/restore")
async def restore_snap(doc_id: str, sid: str, user: str = Depends(me)):
    need_edit(user, doc_id)
    con = db.connect()
    try:
        s = con.execute("SELECT content FROM snapshots WHERE id=? AND doc_id=?", (sid, doc_id)).fetchone()
        if not s:
            raise HTTPException(404, "Stand weg")
        cur = con.execute("SELECT content FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not cur:
            raise HTTPException(404, "Doc weg")
        con.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?", (s["content"], db.now_iso(), doc_id))
        con.commit()
    finally:
        con.close()
    auto = sync.room_text(doc_id)
    auto_snap(doc_id, auto if auto is not None else cur["content"], "Vor Wiederherstellung")  # kein Weg zurück ohne Netz
    await sync.replace_text(doc_id, s["content"])  # Live-Room füllen + an alle funken
    return {"ok": True}


@app.delete("/api/docs/{doc_id}/snapshots/{sid}")
def delete_snap(doc_id: str, sid: str, user: str = Depends(me)):
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Nur Owner kann Stände löschen")
    con = db.connect()
    try:
        con.execute("DELETE FROM snapshots WHERE id=? AND doc_id=?", (sid, doc_id))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.get("/api/docs/{doc_id}/members")
def list_members(doc_id: str, user: str = Depends(me)):
    need_access(user, doc_id)  # für @-Mentions im Kommentar
    con = db.connect()
    try:
        d = con.execute("SELECT owner FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, "Doc weg")
        rows = con.execute("SELECT username FROM shares WHERE doc_id=? ORDER BY username", (doc_id,)).fetchall()
        return {"members": [d["owner"], *[r["username"] for r in rows]]}
    finally:
        con.close()


@app.get("/api/search")
def search_docs(req: Request, q: str = "", user: str = Depends(me)):
    limited(req, "search")
    q = q.strip()[:50]
    if len(q) < 2:
        return {"hits": []}
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT d.id, d.title, d.owner, d.content FROM docs d LEFT JOIN shares s "
            "ON s.doc_id=d.id AND s.username=? WHERE d.trashed=0 AND (d.owner=? OR s.username=?) "
            "AND (d.title LIKE ? ESCAPE '\\' OR d.content LIKE ? ESCAPE '\\') "
            "ORDER BY d.updated_at DESC LIMIT 20", (user, user, user, like, like)).fetchall()
        hits = []
        for r in rows:
            live = sync.room_text(r["id"])  # Room ist neuer als DB (2s-Save), sonst springt Suche daneben
            txt = live if live is not None else r["content"]
            i = txt.lower().find(q.lower())
            snippet = ("…" + txt[max(0, i - 40):i + 80].replace("\n", " ") + "…") if i >= 0 else ""
            hits.append({"id": r["id"], "title": r["title"], "owner": r["owner"],
                         "snippet": snippet, "pos": i})
        return {"hits": hits}
    finally:
        con.close()


def zip_name(s: str, ext: str = "") -> str:
    n = re.sub(r"[^A-Za-z0-9äöüÄÖÜß._-]+", "_", s.strip())[:80].strip("._") or "dokument"
    return n + ext


@app.get("/api/export.zip")
def export_zip(req: Request, user: str = Depends(me)):
    limited(req, "export")  # ZIP baut alles: eng deckeln
    con = db.connect()
    try:
        docs = con.execute("SELECT id, title, content, folder FROM docs WHERE owner=? AND trashed=0 "
                           "ORDER BY folder, title", (user,)).fetchall()
        buf = io.BytesIO()
        used = set()  # doppelte Titel: nummerieren statt überschreiben
        total = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for d in docs:
                pre = (zip_name(d["folder"]) + "/") if d["folder"] else ""
                base = zip_name(d["title"])
                name, i = base, 2
                while (pre + name + ".typ").lower() in used:
                    name, i = f"{base} {i}", i + 1
                used.add((pre + name + ".typ").lower())
                live = sync.room_text(d["id"])  # Room neuer als DB (s. duplicate/snapshot)
                txt = live if live is not None else d["content"]
                total += len(txt)
                if total > EXPORT_MAX:
                    raise HTTPException(413, "Export zu groß (max 100 MB)")
                z.writestr(pre + name + ".typ", txt)
                fdir = FILES_DIR / d["id"]
                if fdir.is_dir():
                    for p in sorted(fdir.iterdir()):
                        if p.is_file() and p.stat().st_size <= 10 * 1024 * 1024:
                            total += p.stat().st_size
                            if total > EXPORT_MAX:
                                raise HTTPException(413, "Export zu groß (max 100 MB)")
                            z.writestr(pre + name + "-dateien/" + p.name, p.read_bytes())
        return Response(content=buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": "attachment; filename=typst-backup.zip"})
    finally:
        con.close()


@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def api_fallback(full_path: str):
    raise HTTPException(404, "API weg")


@app.get("/healthz")
def healthz():
    return {"ok": True}


FRONT_FILES = {"vendor-cm.js", "manifest.json", "sw.js", "icon-192.png", "icon-512.png", "icon.svg"}


@app.get("/")
def frontend_root():
    return FileResponse(str(ROOT / "index.html"))


@app.get("/{name}")
def frontend_file(name: str):
    if name in FRONT_FILES:
        p = ROOT / name
        if p.is_file():
            return FileResponse(str(p))
    raise HTTPException(404, "Not found")