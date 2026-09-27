from __future__ import annotations

import base64
import hmac
import logging
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from backend import auth, config, db, ratelimit, sync
from backend.constants import (
    EXPORT_MAX,
    FOLDER_MAX,
    INVITE_SECONDS,
    LOCK_NAME,
    MAX_TXT,
    RATE_DEFAULTS,
    SNAP_EVERY,
    SNAP_MAX,
    TITLE_MAX,
    UPLOAD_MAX,
)

log = logging.getLogger("typst.main")
COOKIE = auth.COOKIE
NAME_RE = r"[A-Za-z0-9_-]{2,20}"
MIN_PW = 8
MAX_PW = 200
RATE_SCOPES = dict(RATE_DEFAULTS)

ROOT = Path(__file__).resolve().parent.parent
try:
    FILES_DIR = config.load().DATA_DIR / "files"
except Exception as e:
    log.warning("config DATA_DIR missing, fallback data/files: %s", e)
    FILES_DIR = ROOT / "data" / "files"
ALLOWED_IMG = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".pdf", ".typ", ".bib", ".csv"}
TEXT_SUFFIX = {".typ", ".bib", ".csv"}

_LOCK_FH = None
_DOC_LOCKS: dict[str, threading.Lock] = {}
_DOC_LOCKS_GUARD = threading.Lock()
_EXPORT_LOCKS: dict[str, threading.Lock] = {}


def _doc_lock(key: str) -> threading.Lock:
    with _DOC_LOCKS_GUARD:
        lock = _DOC_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _DOC_LOCKS[key] = lock
        return lock


def _export_lock(user: str) -> threading.Lock:
    with _DOC_LOCKS_GUARD:
        lock = _EXPORT_LOCKS.get(user)
        if lock is None:
            lock = threading.Lock()
            _EXPORT_LOCKS[user] = lock
        return lock


def _drop_doc_locks(doc_id: str) -> None:
    # Drop per-doc locks when the room is gone (no reaper thread).
    with _DOC_LOCKS_GUARD:
        _DOC_LOCKS.pop(f"upload:{doc_id}", None)
        _DOC_LOCKS.pop(f"ws:{doc_id}", None)


def _drop_user_locks(user: str) -> None:
    # Drop per-user locks when the user is gone (no reaper thread).
    with _DOC_LOCKS_GUARD:
        _DOC_LOCKS.pop(f"dup:{user}", None)
        _EXPORT_LOCKS.pop(user, None)


def _lock_path() -> Path:
    try:
        return Path(str(db.DB_PATH)).parent / LOCK_NAME
    except Exception:
        pass
    try:
        return config.load().DATA_DIR / LOCK_NAME
    except Exception:
        return ROOT / "data" / LOCK_NAME


def _acquire_single_lock() -> None:
    global _LOCK_FH
    if _LOCK_FH is not None:
        return
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    msvcrt_mod: Any = None
    fcntl_mod: Any = None
    try:
        import msvcrt as _msvcrt
        msvcrt_mod = _msvcrt
    except ImportError:
        pass
    try:
        import fcntl as _fcntl
        fcntl_mod = _fcntl
    except ImportError:
        pass
    fh = open(path, "a+b")
    try:
        fh.seek(0, 2)
        if fh.tell() == 0:
            fh.write(b"\0")
            fh.flush()
        if fcntl_mod is not None:
            fcntl_mod.flock(fh.fileno(), fcntl_mod.LOCK_EX | fcntl_mod.LOCK_NB)
        elif msvcrt_mod is not None:
            fh.seek(0)
            msvcrt_mod.locking(fh.fileno(), msvcrt_mod.LK_NBLCK, 1)
        else:
            raise OSError("no file lock available")
        _LOCK_FH = fh
    except Exception:
        try:
            fh.close()
        except Exception:
            pass
        log.error("another instance is already running, exit")
        raise SystemExit(1)


def _release_single_lock() -> None:
    global _LOCK_FH
    fh, _LOCK_FH = _LOCK_FH, None
    if fh is None:
        return
    try:
        fcntl_mod: Any = None
        msvcrt_mod: Any = None
        try:
            import fcntl as _fcntl
            fcntl_mod = _fcntl
        except ImportError:
            pass
        try:
            import msvcrt as _msvcrt
            msvcrt_mod = _msvcrt
        except ImportError:
            pass
        try:
            if fcntl_mod is not None:
                fcntl_mod.flock(fh.fileno(), fcntl_mod.LOCK_UN)
            elif msvcrt_mod is not None:
                fh.seek(0)
                msvcrt_mod.locking(fh.fileno(), msvcrt_mod.LK_UNLCK, 1)
        except Exception:
            pass
        fh.close()
    except Exception:
        pass


TUTORIAL = """\
// Short Typst example paper (fits on one A4 page)

#set page(paper: "a4", margin: (x: 2.2cm, y: 1.8cm), numbering: "1")
#set text(font: "New Computer Modern", size: 11pt)
#set par(justify: true)
#set heading(numbering: "1.")

#align(center)[
  #text(15pt, weight: "bold")[A Short Example Paper in Typst]

  #v(0.5em)
  Alice Example · Bob Typst

  #v(0.2em)
  #text(9.5pt)[Department of Computer Science · Example University]
]

#v(0.8em)

#align(center)[Abstract]
This short document demonstrates the main Typst features needed for a paper: headings, paragraphs, mathematics, a table, a simple diagram and a code snippet.

= Introduction
Typst is a modern typesetting system. You write text normally. \\
Italic and bold work directly.

Here is a small code example:

#let greet(name) = [Hello, #name!]
#greet("World")

= Mathematics
Inline math: $E = m c^2$.

Display math:
$
  integral_0^infinity e^(-x^2) dif x = sqrt(pi)/2
$

= Table and Diagram

#figure(
  table(
    columns: 3,
    align: (left, center, right),
    stroke: 0.5pt,
    inset: 5pt,
    [Name], [Value], [Unit],
    [Speed of light], [$c$], [$3 times 10^8$ m/s],
    [Planck constant], [$h$], [$6.626 times 10^(-34)$ J·s],
  ),
  caption: [Fundamental constants.],
)

// Centered bar diagram with dark gray bars
#figure(
  align(center)[
    #let data = (
      ("A", 40),
      ("B", 65),
      ("C", 30),
      ("D", 80),
    )
    #let max-h = 2.2cm
    #let bar-w = 1.1cm
    #let gap = 0.45cm

    #box(width: 7.2cm, height: 3.1cm)[
      #for (i, (label, value)) in data.enumerate() {
        let h = max-h * (value / 100)
        place(
          left + bottom,
          dx: 0.6cm + i * (bar-w + gap),
          dy: -0.35cm,
          rect(
            width: bar-w,
            height: h,
            fill: luma(70),
            stroke: 0.5pt + luma(40),
            radius: 2pt,
          )
        )
        place(
          left + bottom,
          dx: 0.75cm + i * (bar-w + gap),
          dy: -h - 0.55cm,
          text(8pt)[#value]
        )
        place(
          left + bottom,
          dx: 0.9cm + i * (bar-w + gap),
          dy: -0.05cm,
          text(9pt)[#label]
        )
      }
      #place(
        left + bottom,
        dx: 0.4cm,
        dy: -0.35cm,
        line(length: 6.4cm, stroke: 0.6pt)
      )
    ]
  ],
  caption: [Simple bar diagram created with pure Typst.],
)

= Conclusion
This example shows the essential Typst syntax and fits on a single A4 page.
"""

db.init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging as _logging
    import os as _os
    import sys as _sys
    for _k in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        try:
            if int((_os.getenv(_k, "1") or "1").strip()) > 1:
                _logging.getLogger("typst.sync").warning(
                    "multi-worker detected (%s=%s): sync rooms are in-memory, use --workers 1",
                    _k, _os.getenv(_k))
                log.error("multi-worker not supported, exit (use --workers 1)")
                _sys.exit(1)
                break
        except ValueError:
            continue
    _acquire_single_lock()
    try:
        yield
    finally:
        try:
            sync.flush_all()
        except Exception:
            pass
        _release_single_lock()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_400(req: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": "Invalid request"})


@app.middleware("http")
async def no_cache_html(req: Request, call: Any):
    if req.url.path.startswith(("/backend", "/data", "/.git", "/tests", "/.github",
                                   "/config.toml", "/.env", "/app.db", "/Dockerfile", "/compose")):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    if req.method in ("POST", "PUT", "DELETE", "PATCH"):
        o = req.headers.get("origin", "") or req.headers.get("referer", "")
        if o:
            host = (req.headers.get("host", "") or "").split(",")[-1].strip().lower()
            if urlparse(o).netloc.lower() != host:
                log.warning("csrf-block %s", req.url.path)
                return JSONResponse({"detail": "Forbidden"}, status_code=403)
    res = await call(req)
    if req.url.path == "/" or req.url.path.endswith((".html", ".js")) or req.url.path.startswith("/api/"):
        res.headers["Cache-Control"] = "no-store"
    res.headers["X-Content-Type-Options"] = "nosniff"
    res.headers["X-Frame-Options"] = "DENY"
    res.headers["Referrer-Policy"] = "no-referrer"
    res.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' https://cdnjs.cloudflare.com https://esm.sh https://cdn.jsdelivr.net; "
        "connect-src 'self' https://esm.sh https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://packages.typst.org wss: ws:; worker-src 'self' blob: https://cdnjs.cloudflare.com; img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; font-src 'self' data:; base-uri 'self'; object-src 'none'; frame-ancestors 'none';")
    proto = req.url.scheme
    fwd_proto = ""
    try:
        if config.load().TRUST_PROXY:
            fwd_proto = (req.headers.get("x-forwarded-proto", "") or "").split(",")[-1].strip().lower()
    except Exception:
        pass
    if proto == "https" or fwd_proto == "https":
        res.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    res.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return res


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


def client_ip(req: Request) -> str:
    try:
        if config.load().TRUST_PROXY:
            fwd = req.headers.get("x-forwarded-for", "")
            if len(fwd) > 1000:
                log.warning("suspicious X-Forwarded-For length (%d)", len(fwd))
            if fwd.strip():
                return fwd.split(",")[0].strip()[:45] or "?"
    except Exception:
        pass
    return req.client.host if req.client else "?"


def limited(req: Request, scope: str, key: str = "") -> None:
    lim, win = RATE_SCOPES.get(scope, (30, 60))
    try:
        cfg = config.load()
        attr = f"RATE_{scope.upper()}_PER_MIN"
        if scope == "register":
            lim = cfg.RATE_REGISTER_PER_HOUR
            win = 3600
        elif hasattr(cfg, attr):
            lim = int(getattr(cfg, attr))
    except Exception:
        pass
    if not ratelimit.allow(f"{scope}:{client_ip(req)}", lim, win):
        log.warning("rate-limit %s (ip-bucket)", scope)
        raise HTTPException(429, "Too many requests - try again shortly")
    if key and not ratelimit.allow(f"{scope}:user:{key}", lim, win):
        log.warning("rate-limit %s (user-bucket)", scope)
        raise HTTPException(429, "Too many requests - try again shortly")


def busy_503(what: str, e: Exception) -> HTTPException:
    log.warning("%s busy: %s", what, e)
    return HTTPException(503, "Database busy, try again")


@app.exception_handler(sqlite3.OperationalError)
async def sqlite_busy_handler(req: Request, exc: sqlite3.OperationalError) -> JSONResponse:
    # single place instead of 20 try-blocks: locked/busy -> 503, rest -> 500
    msg = str(exc).lower()
    if "locked" in msg or "busy" in msg:
        e = busy_503("db", exc)
        return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
    log.warning("db operational: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Database error"})


def user_bytes(user: str) -> int:
    con = db.connect()
    try:
        r = con.execute("SELECT COALESCE(SUM(LENGTH(CAST(content AS BLOB))),0) + COALESCE(SUM(LENGTH(yjs)),0) AS n FROM docs WHERE owner=?", (user,)).fetchone()
        total = int(r["n"] or 0)
        s = con.execute("SELECT COALESCE(SUM(LENGTH(CAST(s.content AS BLOB))),0) AS n FROM snapshots s "
                        "JOIN docs d ON d.id=s.doc_id WHERE d.owner=?", (user,)).fetchone()
        total += int(s["n"] or 0)
        t = con.execute("SELECT COALESCE(SUM(LENGTH(CAST(content AS BLOB))),0) AS n FROM templates WHERE owner=?", (user,)).fetchone()
        total += int(t["n"] or 0)
        a = con.execute("SELECT avatar FROM users WHERE name=?", (user,)).fetchone()
        if a and a["avatar"]:
            total += len(a["avatar"].encode("utf-8"))
        ids = [x["id"] for x in con.execute("SELECT id FROM docs WHERE owner=?", (user,)).fetchall()]
    finally:
        con.close()
    for did in ids:
        d = FILES_DIR / did
        if d.is_dir():
            try:
                entries = list(d.iterdir())
            except OSError:
                continue
            for p in entries:
                if p.is_file():
                    try:
                        total += p.stat().st_size
                    except OSError:
                        pass
    return total


def _quota_cap() -> int:
    try:
        return config.load().MAX_BYTES_PER_USER
    except Exception:
        return 524288000


def check_quota(user: str, extra: int) -> None:
    if user_bytes(user) + extra > _quota_cap():
        raise HTTPException(413, "Quota exceeded")


def _owner(doc_id: str, fallback: str) -> str:
    con = db.connect()
    try:
        r = con.execute("SELECT owner FROM docs WHERE id=?", (doc_id,)).fetchone()
        return r["owner"] if r else fallback
    finally:
        con.close()


def need_edit(user: str, doc_id: str) -> None:
    if need_access(user, doc_id) not in ("owner", "editor"):
        raise HTTPException(403, "Reviewer can only comment")
    if db.is_trashed(doc_id):
        raise HTTPException(410, "In trash - restore first")


class Login(BaseModel):
    username: str = Field(max_length=20)
    password: str = Field(max_length=200)


class Register(BaseModel):
    username: str = Field(max_length=20)
    password: str = Field(max_length=200)
    invite: str = Field(default="", max_length=200)


class DocCreate(BaseModel):
    title: str = Field(default="New document", max_length=100)
    content: str = Field(default="", max_length=200001)
    folder: str = Field(default="", max_length=40)


class DocSave(BaseModel):
    content: str = Field(max_length=200001)
    force: bool = False


class TitleSet(BaseModel):
    title: str = Field(max_length=100)


class TplSave(BaseModel):
    name: str = Field(max_length=100)
    content: str = Field(default="", max_length=200001)
    folder: str = Field(default="", max_length=40)


class Share(BaseModel):
    username: str = Field(max_length=20)
    role: str = Field(default="reviewer", max_length=20)


class CommentNew(BaseModel):
    anchor: int = Field(default=0, ge=0, le=10000000)
    text: str = Field(max_length=2001)
    parent_id: str | None = Field(default=None, max_length=100)
    quote: str = Field(default="", max_length=2000)


class AnchorSet(BaseModel):
    anchor: int = Field(ge=0, le=10000000)


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


class SnapRestore(BaseModel):
    force: bool = False


class FileText(BaseModel):
    content: str = Field(default="", max_length=200001)


class InviteNew(BaseModel):
    role: str = Field(default="reviewer", max_length=20)  # editor | reviewer


class JoinBody(BaseModel):
    token: str = Field(max_length=200)  # POST body preferred: token never in URL/access log


class PwChange(BaseModel):
    old: str = Field(max_length=200)
    new: str = Field(max_length=200)


class NameChange(BaseModel):
    name: str = Field(max_length=20)
    password: str = Field(max_length=200)


class PwOnly(BaseModel):
    password: str = Field(max_length=200)


class AvatarSet(BaseModel):
    img: str = Field(default="", max_length=300000)


@app.post("/api/login")
def login(b: Login, res: Response, req: Request) -> dict:
    name = b.username.strip()
    limited(req, "login", name.lower())
    token = auth.create_session(name, b.password)
    if not token:
        log.warning("login failed")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid login")
    set_cookie(res, req, token)
    return {"user": name}


def _cookie_secure(req: Request) -> bool:
    cfg = config.load()
    if not cfg.TRUST_PROXY and req.headers.get("x-forwarded-proto"):
        log.warning("X-Forwarded-Proto seen but TRUST_PROXY=false, ignoring proxy headers")
    if cfg.COOKIE_SECURE == "true":
        return True
    if cfg.COOKIE_SECURE == "false":
        return False
    proto = req.url.scheme
    if cfg.TRUST_PROXY:
        proto = ((req.headers.get("x-forwarded-proto", "") or proto).split(",")[-1].strip().lower() or proto)
    return proto == "https"


def set_cookie(res: Response, req: Request, token: str) -> None:
    cfg = config.load()
    res.set_cookie(COOKIE, token, max_age=min(max(cfg.SESSION_SECONDS, 3600), 90 * 86400),
                   path="/", httponly=True, samesite="lax", secure=_cookie_secure(req))


def clear_cookie(res: Response, req: Request) -> None:
    res.delete_cookie(COOKIE, path="/", samesite="lax", secure=_cookie_secure(req), httponly=True)


@app.post("/api/register")
def register(b: Register, res: Response, req: Request) -> dict:
    name = b.username.strip()
    limited(req, "register", name.lower())
    cfg = config.load()
    if cfg.REGISTRATION not in ("open", "invite-only", "closed"):
        log.warning("register blocked (bad mode)")
        raise HTTPException(403, "Registration disabled")
    if not re.fullmatch(NAME_RE, name):
        raise HTTPException(400, "Name: 2-20 chars, letters/numbers/_-")
    if not MIN_PW <= len(b.password) <= MAX_PW:
        raise HTTPException(400, "Password: 8-200 chars")
    with _doc_lock("register"):
        con = db.connect()
        try:
            try:
                con.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as e:
                raise busy_503("register", e)
            try:
                empty = con.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0
                if not empty:
                    if cfg.REGISTRATION == "closed":
                        con.execute("ROLLBACK")
                        log.warning("register blocked (closed)")
                        raise HTTPException(403, "Registration disabled")
                    elif cfg.REGISTRATION == "invite-only" and (not cfg.REGISTRATION_INVITE_TOKEN or not hmac.compare_digest(b.invite, cfg.REGISTRATION_INVITE_TOKEN)):
                        con.execute("ROLLBACK")
                        log.warning("register blocked (invite)")
                        raise HTTPException(403, "Invalid invite code")
                if con.execute("SELECT 1 FROM users WHERE name=?", (name,)).fetchone():
                    con.execute("ROLLBACK")
                    auth.check_password("dummy-timing", auth.DUMMY_HASH)
                    raise HTTPException(400, "Registration failed")
                con.execute("INSERT INTO users (name, hash) VALUES (?,?)", (name, auth.hash_password(b.password)))
                did, now = db.new_id("d_"), db.now_iso()
                con.execute("INSERT INTO docs (id, owner, title, content, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                            (did, name, "Tutorial", TUTORIAL, now, now))
                con.commit()
                if empty:
                    log.warning("first user created — set REGISTRATION_INVITE_TOKEN afterwards")
            except HTTPException:
                raise
            except sqlite3.IntegrityError:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise HTTPException(400, "Registration failed")
            except sqlite3.OperationalError as e:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise busy_503("register", e)
        finally:
            con.close()
    token = auth.mint(name)
    set_cookie(res, req, token)
    return {"user": name}


@app.post("/api/logout")
async def logout(req: Request, res: Response):
    tok = req.cookies.get(COOKIE, "")
    user = None
    if tok:
        try:
            user = auth.verify_session(tok)
        except Exception:
            user = None
        # Drop cached session first so logged-out tokens die immediately.
        hit = sync._sess_cache.pop(tok, None)
        if hit and hit[0]:
            sync.drop_sess_cache(hit[0])
        auth.delete_session(tok)
    if user:
        await sync.kick_all(user)
    clear_cookie(res, req)
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
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong password")
    finally:
        con.close()


@app.post("/api/me/password")
async def change_password(b: PwChange, req: Request, res: Response, user: str = Depends(me)):
    limited(req, "pw")
    check_pw(user, b.old)
    if not MIN_PW <= len(b.new) <= MAX_PW:
        raise HTTPException(400, "Password: 8-200 chars")
    new_tok = auth.mint(user)
    con = db.connect()
    try:
        con.execute("UPDATE users SET hash=? WHERE name=?", (auth.hash_password(b.new), user))
        con.execute("DELETE FROM sessions WHERE username=? AND token_hash!=?", (user, auth.sha(new_tok)))
        con.commit()
    finally:
        con.close()
    set_cookie(res, req, new_tok)
    await sync.kick_all(user)
    return {"ok": True}


@app.post("/api/me/name")
async def rename_me(b: NameChange, req: Request, user: str = Depends(me)):
    limited(req, "pw")
    new = b.name.strip()
    if not re.fullmatch(NAME_RE, new):
        raise HTTPException(400, "Name: 2-20 chars, letters/numbers/_-")
    check_pw(user, b.password)
    con = db.connect()
    try:
        if new != user and con.execute("SELECT 1 FROM users WHERE name=?", (new,)).fetchone():
            raise HTTPException(400, "Name taken")
        if new == user:
            return {"user": user}
        row = con.execute("SELECT hash, avatar FROM users WHERE name=?", (user,)).fetchone()
        if not row:
            raise HTTPException(404, "User gone")
        try:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM users WHERE name=?", (new,)).fetchone():
                con.execute("ROLLBACK")
                raise HTTPException(400, "Name taken")
            con.execute("INSERT INTO users (name, hash, avatar) VALUES (?,?,?)",
                        (new, row["hash"], row["avatar"]))
            con.execute("UPDATE sessions SET username=? WHERE username=?", (new, user))
            con.execute("UPDATE docs SET owner=? WHERE owner=?", (new, user))
            con.execute("UPDATE shares SET username=? WHERE username=?", (new, user))
            con.execute("UPDATE comments SET username=? WHERE username=?", (new, user))
            con.execute("UPDATE templates SET owner=? WHERE owner=?", (new, user))
            con.execute("UPDATE folders SET owner=? WHERE owner=?", (new, user))
            con.execute("DELETE FROM users WHERE name=?", (user,))
            con.commit()
        except sqlite3.OperationalError as e:
            log.warning("rename_me %s -> %s busy: %s", user, new, e)
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise HTTPException(503, "Database busy, try again")
        except sqlite3.IntegrityError as e:
            log.warning("rename_me %s -> %s failed: %s", user, new, e)
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise HTTPException(400, "Rename failed")
        await sync.kick_all(user)
        await sync.kick_all(new)
        sync.drop_role_cache(user)
        sync.drop_role_cache(new)
        sync.drop_sess_cache(user)
        sync.drop_sess_cache(new)
        _drop_user_locks(user)
        return {"user": new}
    finally:
        con.close()


@app.post("/api/me/avatar")
def set_avatar(b: AvatarSet, req: Request, user: str = Depends(me)):
    limited(req, "avatar")
    m = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", b.img)
    if not m or len(b.img) > 200_000:
        raise HTTPException(400, "Only PNG/JPEG/WebP as data URL (max 200 KB)")
    check_quota(user, len(b.img.encode("utf-8")))
    con = db.connect()
    try:
        old = con.execute("SELECT avatar FROM users WHERE name=?", (user,)).fetchone()
        old_val = old["avatar"] if old and old["avatar"] else ""
        con.execute("UPDATE users SET avatar=? WHERE name=?", (m.group(1) + ":" + m.group(2), user))
        con.commit()
    finally:
        con.close()
    if user_bytes(user) > _quota_cap():
        con = db.connect()
        try:
            con.execute("UPDATE users SET avatar=? WHERE name=?", (old_val, user))
            con.commit()
        finally:
            con.close()
        raise HTTPException(413, "Quota exceeded")
    return {"ok": True}


@app.delete("/api/me/avatar")
def del_avatar(req: Request, user: str = Depends(me)):
    limited(req, "avatar")
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
        if username != user:
            ok = con.execute(
                "SELECT 1 FROM docs d WHERE d.trashed=0 "
                "AND (d.owner=? OR EXISTS (SELECT 1 FROM shares WHERE doc_id=d.id AND username=?)) "
                "AND (d.owner=? OR EXISTS (SELECT 1 FROM shares WHERE doc_id=d.id AND username=?)) "
                "LIMIT 1", (user, user, username, username)).fetchone()
            if not ok:
                raise HTTPException(404, "No image")
        r = con.execute("SELECT avatar FROM users WHERE name=?", (username,)).fetchone()
        if not r or not r["avatar"]:
            raise HTTPException(404, "No image")
        val = r["avatar"]
        if ":" in val:
            kind, b64 = val.split(":", 1)
            mime = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}.get(kind, "image/png")
        else:
            b64, mime = val, "image/png"
        try:
            raw = base64.b64decode(b64)
        except Exception:
            raise HTTPException(404, "No image")
        return Response(content=raw, media_type=mime,
                        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"}) # busted via ?v=, no limit needed
    finally:
        con.close()


@app.post("/api/me/delete")
async def delete_me(b: PwOnly, req: Request, res: Response, user: str = Depends(me)):
    limited(req, "pw")
    check_pw(user, b.password)
    con = db.connect()
    try:
        owned = [r["id"] for r in con.execute("SELECT id FROM docs WHERE owner=?", (user,)).fetchall()]
        con.execute("DELETE FROM comments WHERE username=? AND parent_id IS NOT NULL", (user,))
        con.execute("UPDATE comments SET username='[deleted]' WHERE username=?", (user,))
        con.execute("DELETE FROM users WHERE name=?", (user,))
        con.commit()
    finally:
        con.close()
    for did in owned:
        await sync.drop(did)
        try:
            shutil.rmtree(FILES_DIR / did, ignore_errors=True)
        except OSError:
            log.warning("delete_me %s: rmtree failed", did)
    await sync.kick_all(user)
    _drop_user_locks(user)
    if req.cookies.get(COOKIE):
        auth.delete_session(req.cookies[COOKIE])
    clear_cookie(res, req)
    return {"ok": True}


@app.websocket("/ws/{doc_id}")
async def ws_doc(ws: WebSocket, doc_id: str):
    try:
        check_doc_id(doc_id)
    except HTTPException:
        await ws.accept()
        await ws.close(code=4403)
        return
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
    try:
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
    n0 = name.strip()
    if len(n0) > FOLDER_MAX:
        raise HTTPException(400, "Folder name too long")
    n = n0[:FOLDER_MAX]
    if not n:
        raise HTTPException(400, "Empty folder name")
    return n


@app.post("/api/folders")
def make_folder(b: FolderSet, req: Request, user: str = Depends(me)):
    limited(req, "folders")
    n = check_folder_name(b.folder)
    con = db.connect()
    try:
        ensure_folder(con, user, "doc", n)
        con.commit()
        return {"folder": n}
    finally:
        con.close()


@app.post("/api/docs/create")
def create_doc(b: DocCreate, req: Request, user: str = Depends(me)):
    limited(req, "create")
    t = b.title.strip()
    if not t or len(t) > TITLE_MAX:
        raise HTTPException(400, f"Title: 1-{TITLE_MAX} chars")
    if len(b.content) > MAX_TXT:
        raise HTTPException(400, "Doc too large (max 200 KB)")
    try:
        check_quota(user, len(b.content.encode("utf-8")))
    except sqlite3.OperationalError as e:
        raise busy_503("create_doc", e)
    did, now = db.new_id("d_"), db.now_iso()
    con = db.connect()
    try:
        try:
            max_docs = config.load().MAX_DOCS_PER_USER
        except Exception:
            max_docs = 100
        try:
            con.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as e:
            raise busy_503("create_doc", e)
        try:
            if con.execute("SELECT COUNT(*) AS n FROM docs WHERE owner=?", (user,)).fetchone()["n"] >= max_docs:
                con.execute("ROLLBACK")
                raise HTTPException(400, "Too many docs")
            con.execute("INSERT INTO docs (id, owner, title, content, folder, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (did, user, t, b.content,
                         b.folder.strip()[:FOLDER_MAX], now, now))
            ensure_folder(con, user, "doc", b.folder)
            con.commit()
        except HTTPException:
            raise
        except sqlite3.IntegrityError:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise HTTPException(400, "Title already exists")
        except sqlite3.OperationalError as e:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise busy_503("create_doc", e)
        return {"id": did}
    finally:
        con.close()


@app.get("/api/docs/{doc_id}")
def get_doc(doc_id: str, user: str = Depends(me)):
    check_doc_id(doc_id)
    r = need_access(user, doc_id)
    con = db.connect()
    try:
        d = con.execute("SELECT id, owner, title, content, folder, trashed, updated_at FROM docs WHERE id=?",
                        (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, "Doc gone")
        users = con.execute("SELECT username, role FROM shares WHERE doc_id=?", (doc_id,)).fetchall()
        return {**dict(d), "role": r, "shares": [dict(u) for u in users]}
    finally:
        con.close()


def prune_snaps(con: sqlite3.Connection, doc_id: str) -> None:
    con.execute("DELETE FROM snapshots WHERE doc_id=? AND id NOT IN "
                "(SELECT id FROM snapshots WHERE doc_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?)",
                (doc_id, doc_id, SNAP_MAX))


def auto_snap(doc_id: str, content: str, label: str = "") -> None:
    con = db.connect()
    try:
        try:
            con.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            return
        try:
            last = con.execute("SELECT created_at FROM snapshots WHERE doc_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                               (doc_id,)).fetchone()
            cut = (datetime.now(UTC) - timedelta(seconds=SNAP_EVERY)).isoformat()
            if label or not last or last["created_at"] < cut:
                row = con.execute("SELECT owner FROM docs WHERE id=?", (doc_id,)).fetchone()
                if row:
                    try:
                        check_quota(row["owner"], len(content.encode("utf-8")))
                    except HTTPException:
                        con.execute("ROLLBACK")
                        raise
                con.execute("INSERT INTO snapshots (id, doc_id, content, label, created_at) VALUES (?,?,?,?,?)",
                            (db.new_id("s_"), doc_id, content, label, db.now_iso()))
                prune_snaps(con, doc_id)
                con.commit()
            else:
                con.execute("ROLLBACK")
        except HTTPException:
            raise
        except sqlite3.OperationalError:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/save")
async def save_doc(doc_id: str, b: DocSave, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "save")
    need_edit(user, doc_id)
    live = sync.room_text(doc_id)
    if live is not None and live != b.content and not b.force:
        raise HTTPException(409, "Newer live-room state - save with force")
    content = b.content if (live is None or b.force) else live
    if len(content) > MAX_TXT:
        raise HTTPException(400, "Doc too large (max 200 KB)")
    try:
        _c = db.connect()
        try:
            _old = _c.execute("SELECT content FROM docs WHERE id=?", (doc_id,)).fetchone()
        except Exception:
            _old = None
        finally:
            _c.close()
        _old_len = len((_old["content"] or "").encode("utf-8")) if _old and _old["content"] else 0
        check_quota(_owner(doc_id, user), max(0, len(content.encode("utf-8")) - _old_len))
    except sqlite3.OperationalError as e:
        raise busy_503("save_doc", e)
    con = db.connect()
    try:
        try:
            con.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as e:
            raise busy_503("save_doc", e)
        try:
            trashed = con.execute("SELECT trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
            if trashed and trashed["trashed"]:
                con.execute("ROLLBACK")
                raise HTTPException(410, "In trash - restore first")
            con.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?",
                        (content, db.now_iso(), doc_id))
            con.commit()
        except HTTPException:
            raise
        except sqlite3.OperationalError as e:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise busy_503("save_doc", e)
    finally:
        con.close()
    # Post-write quota check with rollback (matches upload/file-text).
    _old_text = (_old["content"] or "") if _old else ""
    try:
        _over = user_bytes(_owner(doc_id, user)) > _quota_cap()
    except sqlite3.OperationalError as e:
        raise busy_503("save_doc", e)
    if _over:
        _rb = db.connect()
        try:
            _rb.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?",
                        (_old_text, db.now_iso(), doc_id))
            _rb.commit()
        finally:
            _rb.close()
        if live is not None:
            await sync.replace_text(doc_id, _old_text)
        raise HTTPException(413, "Quota exceeded")
    if b.force:
        await sync.replace_text(doc_id, content)
    elif live is None:
        if not sync.persist(doc_id):
            db.clear_room_state(doc_id)
    else:
        sync.persist(doc_id)
    try:
        auto_snap(doc_id, content)
    except HTTPException as e:
        log.warning("save_doc snap: %s", e.detail)
    return {"ok": True}


@app.post("/api/docs/{doc_id}/rename")
def rename_doc(doc_id: str, b: TitleSet, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "save")  # reuse save scope (no dedicated rename scope)
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can rename")
    t = b.title.strip()
    if not t or len(t) > TITLE_MAX:
        raise HTTPException(400, f"Title: 1-{TITLE_MAX} chars")
    con = db.connect()
    try:
        con.execute("UPDATE docs SET title=?, updated_at=? WHERE id=?", (t, db.now_iso(), doc_id))
        con.commit()
        return {"ok": True}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Title already exists")
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
def save_template(b: TplSave, req: Request, user: str = Depends(me)):
    limited(req, "save")  # reuse save scope (no dedicated template scope)
    n = re.sub(r"[^A-Za-z0-9._-]", "_", Path(b.name or "").name.strip().lstrip("."))[:100]
    if not n.endswith(".typ") or not b.content.strip() or len(b.content) > MAX_TXT:
        raise HTTPException(400, "Only .typ with content (max 200 KB)")
    try:
        _c = db.connect()
        try:
            _old = _c.execute("SELECT content FROM templates WHERE owner=? AND name=?", (user, n)).fetchone()
        except Exception:
            _old = None
        finally:
            _c.close()
        _old_len = len((_old["content"] or "").encode("utf-8")) if _old and _old["content"] else 0
        check_quota(user, max(0, len(b.content.encode("utf-8")) - _old_len))
    except sqlite3.OperationalError as e:
        raise busy_503("save_template", e)
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
def delete_template(name: str, req: Request, user: str = Depends(me)):
    limited(req, "files")  # reuse files scope (no dedicated template scope)
    con = db.connect()
    try:
        con.execute("DELETE FROM templates WHERE owner=? AND name=?", (user, name))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/templates/{name}/folder")
def move_template(name: str, b: FolderSet, req: Request, user: str = Depends(me)):
    limited(req, "files")  # reuse files scope (no dedicated template scope)
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
def make_tpl_folder(b: FolderSet, req: Request, user: str = Depends(me)):
    limited(req, "folders")
    n = check_folder_name(b.folder)
    con = db.connect()
    try:
        ensure_folder(con, user, "tpl", n)
        con.commit()
        return {"folder": n}
    finally:
        con.close()


@app.post("/api/tplfolders/rename")
def rename_tpl_folder(b: FolderRename, req: Request, user: str = Depends(me)):
    limited(req, "files")  # reuse files scope (no dedicated template scope)
    old, new = b.old.strip()[:FOLDER_MAX], b.new.strip()[:FOLDER_MAX]
    if not old or not new or old == new:
        raise HTTPException(400, "Empty folder name")
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
def drop_tpl_folder(name: str, req: Request, user: str = Depends(me)):
    limited(req, "files")  # reuse files scope (no dedicated template scope)
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
async def delete_doc(doc_id: str, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "save")  # reuse save scope (no dedicated delete scope)
    r = need_access(user, doc_id, allow_trashed=True)
    if r != "owner":
        raise HTTPException(403, "Only owner can delete")
    con = db.connect()
    try:
        row = con.execute("SELECT trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Doc gone")
        trashed = row["trashed"]
        if not trashed:
            con.execute("UPDATE docs SET trashed=1, updated_at=? WHERE id=?", (db.now_iso(), doc_id))
            con.commit()
            await sync.drop(doc_id)
            _drop_doc_locks(doc_id)
            return {"trashed": True}
        con.execute("DELETE FROM docs WHERE id=?", (doc_id,))
        con.commit()
    finally:
        con.close()
    await sync.drop(doc_id)
    _drop_doc_locks(doc_id)
    try:
        shutil.rmtree(FILES_DIR / doc_id, ignore_errors=True)
    except OSError:
        log.warning("delete_doc %s: rmtree failed", doc_id)
    return {"trashed": False}


@app.post("/api/docs/{doc_id}/restore")
def restore_doc(doc_id: str, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "save")  # reuse save scope (no dedicated restore scope)
    if need_access(user, doc_id, allow_trashed=True) != "owner":
        raise HTTPException(403, "Only owner can restore")
    con = db.connect()
    try:
        cur = con.execute("SELECT folder FROM docs WHERE id=?", (doc_id,)).fetchone()
        if cur is None:
            raise HTTPException(404, "Doc gone")
        fld = cur["folder"] if cur and cur["folder"] else ""
        if fld and not con.execute("SELECT 1 FROM folders WHERE owner=? AND kind='doc' AND name=?",
                                   (user, fld)).fetchone():
            fld = ""
        con.execute("UPDATE docs SET trashed=0, folder=?, updated_at=? WHERE id=?", (fld, db.now_iso(), doc_id))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/folder")
def move_doc(doc_id: str, b: FolderSet, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "files")  # reuse files scope (no dedicated move scope)
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can move")
    if len(b.folder.strip()) > FOLDER_MAX:
        raise HTTPException(400, "Folder name too long")
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
def drop_folder(name: str, req: Request, user: str = Depends(me)):
    limited(req, "folders")
    n = name.strip()[:FOLDER_MAX]
    con = db.connect()
    try:
        con.execute("UPDATE docs SET folder='' WHERE owner=? AND folder=? AND trashed=0", (user, n))
        con.execute("DELETE FROM folders WHERE owner=? AND kind='doc' AND name=?", (user, n))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/folders/rename")
def rename_folder(b: FolderRename, req: Request, user: str = Depends(me)):
    limited(req, "folders")
    if len(b.old.strip()) > FOLDER_MAX or len(b.new.strip()) > FOLDER_MAX:
        raise HTTPException(400, "Folder name too long")
    old, new = b.old.strip()[:FOLDER_MAX], b.new.strip()[:FOLDER_MAX]
    if not old or not new or old == new:
        raise HTTPException(400, "Empty folder name")
    con = db.connect()
    try:
        con.execute("UPDATE docs SET folder=?, updated_at=? WHERE owner=? AND folder=? AND trashed=0",
                    (new, db.now_iso(), user, old))
        con.execute("UPDATE OR IGNORE folders SET name=? WHERE owner=? AND kind='doc' AND name=?",
                    (new, user, old))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/duplicate")
def duplicate_doc(doc_id: str, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "duplicate")
    need_edit(user, doc_id)
    try:
        max_docs = config.load().MAX_DOCS_PER_USER
    except Exception:
        max_docs = 100
    nid, now = db.new_id("d_"), db.now_iso()
    src = FILES_DIR / doc_id
    with _doc_lock(f"dup:{user}"):
        con = db.connect()
        try:
            try:
                con.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as e:
                raise busy_503("duplicate_doc", e)
            try:
                if con.execute("SELECT COUNT(*) AS n FROM docs WHERE owner=?", (user,)).fetchone()["n"] >= max_docs:
                    con.execute("ROLLBACK")
                    raise HTTPException(400, "Too many docs")
                d = con.execute("SELECT title, content, folder, trashed FROM docs WHERE id=?",
                                (doc_id,)).fetchone()
                if not d:
                    con.execute("ROLLBACK")
                    raise HTTPException(404, "Doc gone")
                if d["trashed"]:
                    con.execute("ROLLBACK")
                    raise HTTPException(410, "In trash - restore first")
                base = d["title"] + " (copy)"
                title, i = base, 2
                while con.execute("SELECT 1 FROM docs WHERE owner=? AND title=? COLLATE NOCASE",
                                  (user, title)).fetchone():
                    title, i = f"{base} {i}", i + 1
                    if i > 99:
                        con.execute("ROLLBACK")
                        raise HTTPException(400, "Too many copies")
                live = sync.room_text(doc_id)
                text = live if live is not None else d["content"]
                try:
                    max_files = config.load().MAX_FILES_PER_DOC
                except Exception:
                    max_files = 200
                try:
                    files = [p for p in src.iterdir()
                             if p.is_file() and ".tmp." not in p.name] if src.is_dir() else []
                except OSError:
                    files = []
                if len(files) > max_files:
                    con.execute("ROLLBACK")
                    raise HTTPException(400, "Too many files")
                fbytes = 0
                for p in files:
                    try:
                        fbytes += p.stat().st_size
                    except OSError:
                        pass
                try:
                    check_quota(user, len(text.encode("utf-8")) + fbytes)
                except sqlite3.OperationalError as e:
                    try:
                        con.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise busy_503("duplicate_doc", e)
                except HTTPException:
                    try:
                        con.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise
                try:
                    con.execute("INSERT INTO docs (id, owner, title, content, folder, created_at, updated_at) "
                                "VALUES (?,?,?,?,?,?,?)",
                                (nid, user, title, text, d["folder"], now, now))
                    con.commit()
                except sqlite3.OperationalError as e:
                    try:
                        con.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise busy_503("duplicate_doc", e)
                except sqlite3.IntegrityError:
                    try:
                        con.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise HTTPException(400, "Title already exists")
            finally:
                pass
        finally:
            con.close()
    if src.is_dir():
        try:
            shutil.copytree(src, FILES_DIR / nid, ignore=shutil.ignore_patterns(".*", "*.tmp.*"), dirs_exist_ok=True)
        except (OSError, shutil.Error) as e:
            log.warning("duplicate %s -> %s: copytree failed: %s", doc_id, nid, e)
            try:
                shutil.rmtree(FILES_DIR / nid, ignore_errors=True)
            except OSError:
                pass
            con = db.connect()
            try:
                con.execute("DELETE FROM docs WHERE id=?", (nid,))
                con.commit()
            except Exception as e:
                log.warning("duplicate rollback %s failed: %s", nid, e)
            finally:
                con.close()
            raise HTTPException(500, "Copy failed")
    return {"id": nid}


@app.post("/api/docs/{doc_id}/share")
async def share_doc(doc_id: str, b: Share, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "share")
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can invite")
    if b.role not in ("editor", "reviewer"):
        raise HTTPException(400, "role must be editor or reviewer")
    con = db.connect()
    downgraded = False
    try:
        if not con.execute("SELECT 1 FROM users WHERE name=?", (b.username,)).fetchone():
            raise HTTPException(400, "Sharing failed")
        prev = con.execute("SELECT role FROM shares WHERE doc_id=? AND username=?",
                           (doc_id, b.username)).fetchone()
        con.execute("INSERT INTO shares (doc_id, username, role) VALUES (?,?,?) "
                    "ON CONFLICT (doc_id, username) DO UPDATE SET role=excluded.role",
                    (doc_id, b.username, b.role))
        if prev and prev["role"] != b.role:
            if b.role == "reviewer" and prev["role"] == "editor":
                downgraded = True
                # invites carry no username (token -> doc + role), so per-user delete
                # is impossible without migration; wipe editor links fail-closed.
                con.execute("DELETE FROM invites WHERE doc_id=? AND role='editor'",
                            (doc_id,))
        con.commit()
    finally:
        con.close()
    sync.drop_role_cache(b.username)
    if downgraded:
        await sync.kick_user(doc_id, b.username)
    return {"ok": True}


@app.delete("/api/docs/{doc_id}/share/{username}")
async def unshare_doc(doc_id: str, username: str, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "share")
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can remove")
    con = db.connect()
    try:
        con.execute("DELETE FROM shares WHERE doc_id=? AND username=?", (doc_id, username))
        # invites carry no username (token -> doc + role), so per-user delete is
        # impossible without migration; wipe all links fail-closed (no rejoin).
        con.execute("DELETE FROM invites WHERE doc_id=?", (doc_id,))
        con.commit()
    finally:
        con.close()
    await sync.kick_user(doc_id, username)
    return {"ok": True}


@app.get("/api/docs/{doc_id}/comments")
def list_comments(doc_id: str, user: str = Depends(me)):
    check_doc_id(doc_id)
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
    check_doc_id(doc_id)
    limited(req, "comments")
    need_access(user, doc_id)
    if not b.text.strip() or len(b.text) > 2000:
        raise HTTPException(400, "Comment: 1-2000 chars")
    if b.anchor < 0:
        raise HTTPException(400, "Anchor < 0")
    cid = db.new_id("c_")
    con = db.connect()
    try:
        if b.parent_id:
            p = con.execute("SELECT parent_id FROM comments WHERE id=? AND doc_id=?",
                            (b.parent_id, doc_id)).fetchone()
            if not p:
                raise HTTPException(404, "Thread gone")
            if p["parent_id"]:
                raise HTTPException(400, "Nested replies not allowed")
        con.execute("INSERT INTO comments (id, doc_id, username, anchor, quote, text, parent_id, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (cid, doc_id, user, b.anchor, b.quote.strip()[:500], b.text.strip(), b.parent_id, db.now_iso()))
        con.commit()
        return {"id": cid}
    finally:
        con.close()


@app.delete("/api/docs/{doc_id}/comments/{cid}")
def delete_comment(doc_id: str, cid: str, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "comments")
    role = need_access(user, doc_id)
    con = db.connect()
    try:
        t = con.execute("SELECT username, parent_id FROM comments WHERE id=? AND doc_id=?",
                        (cid, doc_id)).fetchone()
        if not t:
            raise HTTPException(404, "Comment gone")
        if role != "owner" and t["username"] != user:
            raise HTTPException(403, "Only author or owner")
        if t["parent_id"]:
            con.execute("DELETE FROM comments WHERE id=?", (cid,))
        else:
            con.execute("DELETE FROM comments WHERE id=? OR parent_id=?", (cid, cid))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/comments/{cid}/anchor")
def move_comment(doc_id: str, cid: str, b: AnchorSet, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "comments")
    need_access(user, doc_id)
    if b.anchor < 0:
        raise HTTPException(400, "Anchor < 0")
    con = db.connect()
    try:
        r = con.execute("SELECT username FROM comments WHERE id=? AND doc_id=? AND parent_id IS NULL",
                        (cid, doc_id)).fetchone()
        if not r:
            raise HTTPException(404, "Comment gone")
        if r["username"] != user:
            raise HTTPException(403, "Only author")
        con.execute("UPDATE comments SET anchor=? WHERE id=?", (b.anchor, cid))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/comments/{cid}/edit")
def edit_comment(doc_id: str, cid: str, b: CommentEdit, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "comments")
    need_access(user, doc_id)
    if not b.text.strip() or len(b.text.strip()) > 2000:
        raise HTTPException(400, "Comment: 1-2000 chars")
    con = db.connect()
    try:
        r = con.execute("SELECT username FROM comments WHERE id=? AND doc_id=?",
                        (cid, doc_id)).fetchone()
        if not r:
            raise HTTPException(404, "Comment gone")
        if r["username"] != user:
            raise HTTPException(403, "Only author")
        con.execute("UPDATE comments SET text=? WHERE id=?", (b.text.strip(), cid))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/comments/{cid}/resolve")
def resolve_comment(doc_id: str, cid: str, b: ResolveSet, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "comments")
    role = need_access(user, doc_id)
    con = db.connect()
    try:
        r = con.execute("SELECT username, parent_id FROM comments WHERE id=? AND doc_id=?",
                        (cid, doc_id)).fetchone()
        if not r:
            raise HTTPException(404, "Comment gone")
        top = cid if not r["parent_id"] else r["parent_id"]
        a = con.execute("SELECT username FROM comments WHERE id=?", (top,)).fetchone()
        if role != "owner" and (not a or a["username"] != user):
            raise HTTPException(403, "Only author or owner")
        con.execute("UPDATE comments SET resolved=? WHERE id=?", (1 if b.resolved else 0, top))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


def safe_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name or "").name.strip().lstrip("."))[:100]
    if not n or Path(n).suffix.lower() not in ALLOWED_IMG:
        raise HTTPException(400, "Only png/jpg/jpeg/svg/gif/webp/pdf/typ/bib/csv")
    return n


DOC_ID_RE = re.compile(r"^d_[A-Za-z0-9_-]+$")


def check_doc_id(doc_id: str) -> None:
    if not DOC_ID_RE.fullmatch(doc_id or ""):
        raise HTTPException(404, "Document not found")


@app.get("/api/docs/{doc_id}/files")
def list_files(doc_id: str, req: Request, user: str = Depends(me)):
    limited(req, "files_list") # own bucket: preview polls this per render, must not starve uploads
    check_doc_id(doc_id)
    need_access(user, doc_id)
    d = FILES_DIR / doc_id
    out = []
    if d.is_dir():
        try:
            entries = sorted(d.iterdir())
        except OSError as e:
            log.warning("list_files list failed: %s", e)
            raise HTTPException(500, "File list failed")
        for p in entries:
            if p.is_file() and ".tmp." not in p.name:
                try:
                    st = p.stat()
                except OSError as e:
                    log.warning("list_files stat gone %s: %s", p.name, e)
                    continue
                out.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime})
    return {"files": out}


@app.post("/api/docs/{doc_id}/files")
def upload_file(doc_id: str, f: UploadFile, req: Request, user: str = Depends(me)):
    limited(req, "files")
    check_doc_id(doc_id)
    need_edit(user, doc_id)
    n = safe_name(f.filename or "")
    with _doc_lock(f"upload:{doc_id}"):
        return _upload_locked(doc_id, f, n, user)


def _upload_locked(doc_id: str, f: UploadFile, n: str, user: str) -> dict:
    try:
        max_files = config.load().MAX_FILES_PER_DOC
    except Exception:
        max_files = 200
    d = FILES_DIR / doc_id
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning("upload_file mkdir failed: %s", e)
        raise HTTPException(500, "Upload failed")
    try:
        pre = sum(1 for p in d.iterdir() if p.is_file() and p.name != n and ".tmp." not in p.name)
    except OSError as e:
        log.warning("upload_file list failed: %s", e)
        raise HTTPException(500, "File list failed")
    if pre >= max_files:
        raise HTTPException(400, "Too many files")
    tmp = d / f"{n}.tmp.{secrets.token_hex(8)}"
    size = 0
    try:
        with open(tmp, "wb") as fh:
            while True:
                blk = f.file.read(64 * 1024)
                if not blk:
                    break
                size += len(blk)
                if size > UPLOAD_MAX:
                    raise HTTPException(400, "Max 10 MB")
                fh.write(blk)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
    except HTTPException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except OSError as e:
        log.warning("upload_file write failed: %s", e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(500, "Upload failed")
    try:
        check_quota(_owner(doc_id, user), size)
    except sqlite3.OperationalError as e:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise busy_503("upload_file", e)
    except HTTPException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    try:
        old = (d / n).read_bytes() if (d / n).is_file() else None
    except OSError:
        old = None
    try:
        os.replace(tmp, d / n)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    try:
        post = sum(1 for p in d.iterdir() if p.is_file() and ".tmp." not in p.name)
    except OSError as e:
        log.warning("upload_file recount failed: %s", e)
        raise HTTPException(500, "File list failed")
    if post > max_files:
        try:
            if old is not None:
                (d / n).write_bytes(old)
            else:
                (d / n).unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(400, "Too many files")
    try:
        over = user_bytes(_owner(doc_id, user)) > _quota_cap()
    except sqlite3.OperationalError as e:
        raise busy_503("upload_file", e)
    if over:
        try:
            if old is not None:
                (d / n).write_bytes(old)
            else:
                (d / n).unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(413, "Quota exceeded")
    touch_doc(doc_id)
    return {"name": n, "size": size}


@app.get("/api/docs/{doc_id}/files/{name}")
def get_file(doc_id: str, name: str, req: Request, user: str = Depends(me)):
    limited(req, "files")
    check_doc_id(doc_id)
    need_access(user, doc_id)
    p = FILES_DIR / doc_id / safe_name(name)
    if not p.is_file():
        raise HTTPException(404, "File gone")
    if p.suffix.lower() == ".svg":
        try:
            data = p.read_bytes()
        except OSError as e:
            log.warning("get_file gone %s: %s", p.name, e)
            raise HTTPException(404, "File gone")
        return Response(content=data, media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{p.name}"',
                                 "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
    return FileResponse(str(p), filename=p.name,
                        headers={"Content-Disposition": f'attachment; filename="{p.name}"',
                                 "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@app.delete("/api/docs/{doc_id}/files/{name}")
def delete_file(doc_id: str, name: str, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "files")
    need_edit(user, doc_id)
    with _doc_lock(f"upload:{doc_id}"):
        p = FILES_DIR / doc_id / safe_name(name)
        if p.is_file():
            try:
                p.unlink()
            except OSError as e:
                log.warning("delete_file %s gone: %s", p.name, e)
        touch_doc(doc_id)
    return {"ok": True}


def need_text(name: str) -> str:
    n = safe_name(name)
    if Path(n).suffix.lower() not in TEXT_SUFFIX:
        raise HTTPException(400, "Only typ/bib/csv as text")
    return n


def touch_doc(doc_id: str) -> None:
    con = db.connect()
    try:
        try:
            con.execute("UPDATE docs SET updated_at=? WHERE id=?", (db.now_iso(), doc_id))
            con.commit()
        except sqlite3.OperationalError as e:
            raise busy_503("touch_doc", e)
    finally:
        con.close()


@app.get("/api/docs/{doc_id}/files/{name}/text")
def get_file_text(doc_id: str, name: str, req: Request, user: str = Depends(me)):
    limited(req, "save") # same cadence as doc save, not the tight files bucket
    check_doc_id(doc_id)
    need_access(user, doc_id)
    p = FILES_DIR / doc_id / need_text(name)
    if not p.is_file():
        raise HTTPException(404, "File gone")
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        log.warning("get_file_text gone %s: %s", p.name, e)
        raise HTTPException(404, "File gone")
    return {"name": p.name, "content": content}


@app.post("/api/docs/{doc_id}/files/{name}/text")
def save_file_text(doc_id: str, name: str, b: FileText, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "save") # autosave every SAVE_MS, like doc save (files bucket is for up/download)
    need_edit(user, doc_id)
    if len(b.content) > MAX_TXT:
        raise HTTPException(400, "Max 200 KB")
    with _doc_lock(f"upload:{doc_id}"):
        p = FILES_DIR / doc_id / need_text(name)
        try:
            _old_sz = p.stat().st_size if p.is_file() else 0
        except OSError:
            _old_sz = 0
        try:
            check_quota(_owner(doc_id, user), max(0, len(b.content.encode("utf-8")) - _old_sz))
        except sqlite3.OperationalError as e:
            raise busy_503("save_file_text", e)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.warning("save_file_text mkdir failed: %s", e)
            raise HTTPException(500, "Upload failed")
        try:
            old = p.read_bytes() if p.is_file() else None
        except OSError:
            old = None
        tmp = p.parent / f"{p.name}.tmp.{secrets.token_hex(8)}"
        try:
            tmp.write_text(b.content, encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        try:
            over = user_bytes(_owner(doc_id, user)) > _quota_cap()
        except sqlite3.OperationalError as e:
            raise busy_503("save_file_text", e)
        if over:
            try:
                if old is None:
                    p.unlink(missing_ok=True)
                else:
                    p.write_bytes(old)
            except OSError:
                pass
            raise HTTPException(413, "Quota exceeded")
        touch_doc(doc_id)
    return {"ok": True}


@app.post("/api/docs/{doc_id}/invite")
def make_invite(doc_id: str, b: InviteNew, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "invite")
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can invite")
    if b.role not in ("editor", "reviewer"):
        raise HTTPException(400, "role must be editor or reviewer")
    tok = db.new_id("")
    con = db.connect()
    try:
        cut = (datetime.now(UTC) - timedelta(seconds=INVITE_SECONDS)).isoformat()
        if con.execute("SELECT COUNT(*) AS n FROM invites WHERE doc_id=? AND created_at>?",
                       (doc_id, cut)).fetchone()["n"] >= 20:
            raise HTTPException(400, "Too many invites")
        con.execute("INSERT INTO invites (token, doc_id, role, hint, created_at) VALUES (?,?,?,?,?)",
                    (auth.sha(tok), doc_id, b.role, tok[:8], db.now_iso()))
        con.commit()
        return {"token": tok}
    finally:
        con.close()


@app.get("/api/docs/{doc_id}/invites")
def list_invites(doc_id: str, user: str = Depends(me)):
    check_doc_id(doc_id)
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner")
    con = db.connect()
    try:
        cut = (datetime.now(UTC) - timedelta(seconds=INVITE_SECONDS)).isoformat()
        rows = con.execute("SELECT hint, role, created_at FROM invites WHERE doc_id=? AND created_at>? "
                           "ORDER BY created_at", (doc_id, cut)).fetchall()
        return {"invites": [dict(r) for r in rows]}
    finally:
        con.close()


@app.delete("/api/docs/{doc_id}/invites/{hint}")
def drop_invite(doc_id: str, hint: str, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "invite")
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner")
    con = db.connect()
    try:
        n = con.execute("SELECT COUNT(*) AS n FROM invites WHERE doc_id=? AND hint=?", (doc_id, hint)).fetchone()["n"]
        if n != 1:
            raise HTTPException(409, "Ambiguous hint - recreate invites one by one")
        con.execute("DELETE FROM invites WHERE doc_id=? AND hint=?", (doc_id, hint))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/join/{token}")
def join_doc(token: str, req: Request, user: str = Depends(me)):
    raise HTTPException(410, "Use POST /api/join with body")


@app.post("/api/join")
def join_doc_body(b: JoinBody, req: Request, user: str = Depends(me)):
    limited(req, "join")
    return _redeem_invite(b.token.strip(), user)


def _redeem_invite(token: str, user: str) -> dict:
    con = db.connect()
    try:
        inv = con.execute("SELECT doc_id, role, created_at FROM invites WHERE token=?",
                          (auth.sha(token),)).fetchone()
        if not inv:
            inv = con.execute("SELECT doc_id, role, created_at FROM invites WHERE token=?",
                              (token,)).fetchone()
            if inv:
                log.warning("legacy plaintext invite migrated")
                try:
                    con.execute("UPDATE invites SET token=? WHERE token=?", (auth.sha(token), token))
                    con.commit()
                except Exception as e:
                    log.warning("invite migrate failed: %s", e)
        if not inv:
            raise HTTPException(404, "Invite invalid")
        cut = (datetime.now(UTC) - timedelta(seconds=INVITE_SECONDS)).isoformat()
        if (inv["created_at"] or "") < cut:
            con.execute("DELETE FROM invites WHERE token=? OR token=?",
                        (auth.sha(token), token))
            con.commit()
            raise HTTPException(404, "Invite invalid")
        d = con.execute("SELECT owner, trashed FROM docs WHERE id=?", (inv["doc_id"],)).fetchone()
        if not d:
            raise HTTPException(404, "Doc gone")
        if d["trashed"]:
            raise HTTPException(410, "In trash - restore first")
        if d["owner"] != user:
            con.execute("INSERT INTO shares (doc_id, username, role) VALUES (?,?,?) "
                        "ON CONFLICT (doc_id, username) DO NOTHING",
                        (inv["doc_id"], user, inv["role"]))
            con.commit()
        return {"id": inv["doc_id"]}
    finally:
        con.close()


@app.get("/api/docs/{doc_id}/snapshots")
def list_snaps(doc_id: str, user: str = Depends(me)):
    check_doc_id(doc_id)
    need_access(user, doc_id)
    con = db.connect()
    try:
        rows = con.execute("SELECT id, label, created_at, LENGTH(content) AS size FROM snapshots "
                           "WHERE doc_id=? ORDER BY created_at DESC, rowid DESC", (doc_id,)).fetchall()
        return {"snapshots": [dict(r) for r in rows]}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/snapshots")
def make_snap(doc_id: str, b: SnapNew, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "snapshots")
    need_edit(user, doc_id)
    live = sync.room_text(doc_id)
    con = db.connect()
    try:
        row = con.execute("SELECT content FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Doc gone")
        cur = live if live is not None else row["content"]
        check_quota(_owner(doc_id, user), len(cur.encode("utf-8")))
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
    check_doc_id(doc_id)
    need_access(user, doc_id)
    con = db.connect()
    try:
        r = con.execute("SELECT content, label, created_at FROM snapshots WHERE id=? AND doc_id=?",
                        (sid, doc_id)).fetchone()
        if not r:
            raise HTTPException(404, "Snapshot gone")
        return dict(r)
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/snapshots/{sid}/restore")
async def restore_snap(doc_id: str, sid: str, req: Request, user: str = Depends(me),
                       force: bool = False, b: SnapRestore | None = None):
    check_doc_id(doc_id)
    limited(req, "snapshots")
    need_edit(user, doc_id)
    eff = force or (b.force if b else False)  # query or body flag, default safe
    auto = sync.room_text(doc_id)
    con = db.connect()
    try:
        try:
            con.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as e:
            raise busy_503("restore_snap", e)
        try:
            s = con.execute("SELECT content FROM snapshots WHERE id=? AND doc_id=?", (sid, doc_id)).fetchone()
            if not s:
                con.execute("ROLLBACK")
                raise HTTPException(404, "Snapshot gone")
            cur = con.execute("SELECT content, trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
            if not cur:
                con.execute("ROLLBACK")
                raise HTTPException(404, "Doc gone")
            if cur["trashed"]:
                con.execute("ROLLBACK")
                raise HTTPException(410, "In trash - restore first")
            if auto is not None and auto != (cur["content"] or "") and not eff:
                con.execute("ROLLBACK")
                raise HTTPException(409, "Document changed meanwhile, retry with force")
            before = auto if auto is not None else cur["content"]
            try:
                check_quota(_owner(doc_id, user), max(0, len((s["content"] or "").encode("utf-8")) - len((cur["content"] or "").encode("utf-8"))))
            except HTTPException:
                con.execute("ROLLBACK")
                raise
            con.execute("INSERT INTO snapshots (id, doc_id, content, label, created_at) VALUES (?,?,?,?,?)",
                        (db.new_id("s_"), doc_id, before, "Before restore", db.now_iso()))
            prune_snaps(con, doc_id)
            con.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?", (s["content"], db.now_iso(), doc_id))
            con.commit()
        except HTTPException:
            raise
        except sqlite3.OperationalError as e:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise busy_503("restore_snap", e)
    finally:
        con.close()
    await sync.replace_text(doc_id, s["content"])
    return {"ok": True}


@app.delete("/api/docs/{doc_id}/snapshots/{sid}")
def delete_snap(doc_id: str, sid: str, req: Request, user: str = Depends(me)):
    check_doc_id(doc_id)
    limited(req, "snapshots")
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can delete snapshots")
    con = db.connect()
    try:
        con.execute("DELETE FROM snapshots WHERE id=? AND doc_id=?", (sid, doc_id))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.get("/api/docs/{doc_id}/members")
def list_members(doc_id: str, user: str = Depends(me)):
    check_doc_id(doc_id)
    need_access(user, doc_id)
    con = db.connect()
    try:
        d = con.execute("SELECT owner FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, "Doc gone")
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
            live = sync.room_text(r["id"])
            txt = live if live is not None else r["content"]
            i = txt.lower().find(q.lower())
            snippet = ("..." + txt[max(0, i - 40):i + 80].replace("\n", " ") + "...") if i >= 0 else ""
            hits.append({"id": r["id"], "title": r["title"], "owner": r["owner"],
                         "snippet": snippet, "pos": i})
        return {"hits": hits}
    finally:
        con.close()


def zip_name(s: str, ext: str = "") -> str:
    n = re.sub(r"[^A-Za-z0-9_.-]+", "_", s.strip())[:80].strip("._") or "document"
    return n + ext


def prune_old_exports(max_age_s: int = 86400) -> None:
    import logging
    try:
        data_dir = config.load().DATA_DIR
    except Exception:
        data_dir = ROOT / "data"
    exp = data_dir / "exports"
    try:
        cut = datetime.now(UTC).timestamp() - max_age_s
        for p in exp.glob("job_*.zip"):
            try:
                if p.is_file() and p.stat().st_mtime < cut:
                    p.unlink()
            except OSError:
                logging.getLogger(__name__).warning("prune export failed: %s", p)
        for p in data_dir.glob("tmp*.zip"):
            try:
                if p.is_file() and p.stat().st_mtime < cut:
                    p.unlink()
            except OSError:
                logging.getLogger(__name__).warning("prune export-tmp failed: %s", p)
    except OSError:
        pass


@app.get("/api/export.zip")
def export_zip(req: Request, background: BackgroundTasks, user: str = Depends(me)):
    limited(req, "export")
    o = req.headers.get("origin", "") or req.headers.get("referer", "")
    if o:
        host = (req.headers.get("host", "") or "").split(",")[-1].strip().lower()
        if urlparse(o).netloc.lower() != host:
            log.warning("csrf-block %s", req.url.path)
            raise HTTPException(403, "Forbidden")
    lock = _export_lock(user)
    if not lock.acquire(blocking=False):
        raise HTTPException(429, "Export already running")
    try:
        return _export_zip(req, background, user)
    finally:
        lock.release()


def _export_zip(req: Request, background: BackgroundTasks, user: str):
    prune_old_exports()
    con = db.connect()
    try:
        docs = [dict(r) for r in con.execute("SELECT id, title, content, folder FROM docs WHERE owner=? AND trashed=0 "
                                             "ORDER BY folder, title", (user,)).fetchall()]
        tpls = [dict(r) for r in con.execute("SELECT name, content FROM templates WHERE owner=? ORDER BY name",
                                             (user,)).fetchall()]
    finally:
        con.close()
    pre_bytes = 0
    for t in tpls:
        pre_bytes += len((t["content"] or "").encode("utf-8"))
        if pre_bytes > EXPORT_MAX:
            raise HTTPException(413, "Export too large (max 100 MB)")
    for d in docs:
        pre_bytes += len(d["content"].encode("utf-8"))
        fdir = FILES_DIR / d["id"]
        if fdir.is_dir():
            try:
                entries = list(fdir.iterdir())
            except OSError:
                entries = []
            for p in entries:
                if p.is_file() and ".tmp." not in p.name:
                    try:
                        sz = p.stat().st_size
                    except OSError:
                        continue
                    if sz <= UPLOAD_MAX:
                        pre_bytes += sz
        if pre_bytes > EXPORT_MAX:
            raise HTTPException(413, "Export too large (max 100 MB)")
    FILES_DIR.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, dir=FILES_DIR.parent, suffix=".zip")
        tmp.close()
    except OSError as e:
        log.warning("export tmp failed: %s", e)
        raise HTTPException(503, "Export busy, try again")
    try:
        used = set()
        total = 0
        skipped: list[str] = []
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as z:
            for d in docs:
                prefix = (zip_name(d["folder"]) + "/") if d["folder"] else ""
                base = zip_name(d["title"])
                name, i = base, 2
                while (prefix + name + ".typ").lower() in used:
                    name, i = f"{base} {i}", i + 1
                used.add((prefix + name + ".typ").lower())
                live = sync.room_text(d["id"])
                txt = live if live is not None else d["content"]
                total += len(txt.encode("utf-8"))
                if total > EXPORT_MAX:
                    raise HTTPException(413, "Export too large (max 100 MB)")
                z.writestr(prefix + name + ".typ", txt)
                fdir = FILES_DIR / d["id"]
                if fdir.is_dir():
                    try:
                        entries = sorted(fdir.iterdir())
                    except OSError:
                        entries = []
                    for p in entries:
                        if not p.is_file() or ".tmp." in p.name:
                            continue
                        try:
                            sz = p.stat().st_size
                        except OSError:
                            continue
                        if sz <= UPLOAD_MAX:
                            total += sz
                            if total > EXPORT_MAX:
                                raise HTTPException(413, "Export too large (max 100 MB)")
                            try:
                                z.write(str(p), prefix + name + "-files/" + p.name)
                            except OSError as e:
                                log.warning("export write gone %s: %s", p.name, e)
                                continue
                        else:
                            skipped.append(prefix + name + "-files/" + p.name)
            for t in tpls:
                raw = (t["name"] or "")
                if raw.lower().endswith(".typ"):
                    raw = raw[:-4]
                base = zip_name(raw)
                name, i = base, 2
                while ("templates/" + name + ".typ").lower() in used:
                    name, i = f"{base} {i}", i + 1
                used.add(("templates/" + name + ".typ").lower())
                txt = t["content"] or ""
                total += len(txt.encode("utf-8"))
                if total > EXPORT_MAX:
                    raise HTTPException(413, "Export too large (max 100 MB)")
                z.writestr("templates/" + name + ".typ", txt)
            if skipped:
                z.writestr("SKIPPED.txt", "Oversized files left out:\n" + "\n".join(skipped) + "\n")
        background.add_task(os.unlink, tmp.name)
        return FileResponse(tmp.name, media_type="application/zip",
                            filename="typst-backup.zip", background=background)
    except Exception as e:
        if not isinstance(e, HTTPException):
            log.warning("export failed")
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def api_fallback(full_path: str):
    raise HTTPException(404, "API gone")


@app.get("/healthz")
def healthz():
    try:
        con = db.connect()
        try:
            con.execute("SELECT 1").fetchone()
        finally:
            con.close()
    except Exception as e:
        log.warning("healthz db failed: %s", e)
        return JSONResponse(status_code=500, content={"ok": False})
    return {"ok": True}


FRONT_FILES = {"vendor-cm.js", "manifest.json", "sw.js", "icon-192.png", "icon-512.png", "icon.svg", "screenshot.png"}


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
