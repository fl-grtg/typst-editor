from __future__ import annotations

import asyncio
import base64
import hmac
import logging
import os
import re
import secrets
import shutil
import sqlite3
import sys
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
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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
from backend.mcp_server import mcp_http_app as _mcp_app
from backend.services import quota as quota_svc

log = logging.getLogger("typst.main")
COOKIE = auth.COOKIE
NAME_RE = r"[A-Za-z0-9_-]{2,20}"
MIN_PW = 8
MAX_PW = 200


def _invite_ok(invite: str, token: str) -> bool:
    """Constant-time invite check; False for empty/non-ASCII (no 500)."""
    try:
        return bool(token) and bool(invite) and hmac.compare_digest(invite.encode(), token.encode())
    except Exception:
        return False

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


def _doc_lock(key: str) -> threading.Lock:
    return _lock_for(_DOC_LOCKS, key)


def _export_lock(user: str) -> threading.Lock:
    return _lock_for(_EXPORT_LOCKS, user)


_SIDEBAR_Q: dict[str, set] = {}  # user -> {(loop, queue)} live /api/events streams (single worker)


def notify_sidebar(user: str) -> None:
    # Own list changed elsewhere (MCP, other tab): wake every open sidebar stream of this user.
    # Def endpoints run in a worker thread: schedule into the loop thread-safely.
    # Coalesce: one pending event is enough, sidebar() refetches everything anyway.
    try:
        _targets = list(_SIDEBAR_Q.get(user, ()))
    except RuntimeError:
        return  # set mutated concurrently; the next mutation notifies again
    for _loop, _q in _targets:
        try:
            if _q.empty():
                _loop.call_soon_threadsafe(_q.put_nowait, "sidebar")
        except Exception as e:
            log.debug("notify_sidebar dropped: %s", e)


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
        except ImportError:
            pass
    try:
        import msvcrt as _m

        _msvcrt = _m
    except ImportError:
        pass
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
    except Exception:
        try:
            fh.close()
        except Exception:
            pass
        log.error("another instance is already running, exit")
        raise SystemExit(1) from None


def _release_single_lock() -> None:
    global _LOCK_FH
    fh, _LOCK_FH = _LOCK_FH, None
    if fh is None:
        return
    try:
        try:
            _filelock(fh, False)
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

def reap_trash_dirs() -> dict[str, int]:
    # B8: delete_me renames FILES_DIR/<id> aside to .trash-<id> before the DB
    # tx. A crash between the steps leaves orphans that user_bytes never
    # counts (and backup still tars). Sweep them at startup (shallow, fast).
    counts = {"restored": 0, "removed": 0, "skipped": 0}
    try:
        entries = list(get_files_dir().iterdir())
    except OSError as e:
        log.warning("trash sweep list failed: %s", e)
        return counts
    trash = [p for p in entries if p.name.startswith(".trash-")]
    if not trash:
        return counts
    con = db.connect()
    try:
        for dst in trash:
            did = dst.name[len(".trash-"):]
            if not did or not dst.is_dir():
                # Stray file, not a staged doc dir: remove it, don't re-warn forever.
                try:
                    dst.unlink()
                except OSError as e:
                    log.warning("trash sweep skipping %s: %s", dst.name, e)
                    counts["skipped"] += 1
                else:
                    counts["removed"] += 1
                continue
            live = get_files_dir() / did
            row = con.execute("SELECT 1 FROM docs WHERE id=?", (did,)).fetchone()
            if row is not None and not live.exists():
                try:
                    dst.rename(live)
                except OSError as e:
                    log.warning("trash sweep restore %s failed: %s", did, e)
                    counts["skipped"] += 1
                else:
                    counts["restored"] += 1
            elif row is None:
                try:
                    shutil.rmtree(dst)
                    if dst.exists():
                        raise OSError("rmtree left files behind")
                except OSError as e:
                    log.warning("trash sweep remove %s failed: %s", did, e)
                    counts["skipped"] += 1
                else:
                    counts["removed"] += 1
            else:
                log.warning("trash sweep leaving ambiguous %s (doc and files both present)", did)
                counts["skipped"] += 1
    finally:
        con.close()
    return counts


db.init_db()


@asynccontextmanager
async def _app_lifespan(app: FastAPI):
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
    try:
        _argv = _sys.argv  # CLI --workers N has the same effect as the env vars above
        if "--workers" in _argv:
            _n = int(_argv[_argv.index("--workers") + 1])
        else:
            _eq = next((a for a in _argv if a.startswith("--workers=")), "")
            _n = int(_eq.split("=", 1)[1]) if _eq else 1
        if _n > 1:
            log.error("multi-worker not supported, exit (use --workers 1)")
            _sys.exit(1)
    except (ValueError, IndexError):
        pass
    try:
        _cfg = config.load()
        if _cfg.REGISTRATION == "invite-only" and not _cfg.REGISTRATION_INVITE_TOKEN:
            log.warning("invite-only without REGISTRATION_INVITE_TOKEN: registration blocked until token is set")
        # Short-token warning already logged by config.load(); enforce the gate here
        # so startup logs always show it (config.load() may serve a cached Config).
        # Fail-closed (B12): refuse to start with a brute-forceable invite token.
        # NOTE: _sys.exit raises SystemExit (BaseException), so it is NOT
        # swallowed by the except Exception below. Empty token path unchanged (B11).
        if _cfg.REGISTRATION_INVITE_TOKEN and len(_cfg.REGISTRATION_INVITE_TOKEN) < 16:
            log.error("REGISTRATION_INVITE_TOKEN too short (%d chars); refusing to start, use >=16 chars (openssl rand -hex 32)",
                        len(_cfg.REGISTRATION_INVITE_TOKEN))
            _sys.exit(1)
    except Exception:
        pass
    # Paths resolve lazily (db.get_db_path/get_files_dir follow DATA_DIR).
    _acquire_single_lock()
    try:
        log.info("trash sweep: %s", reap_trash_dirs())
    except Exception as e:
        log.warning("trash sweep failed: %s", e)
    try:
        yield
    finally:
        try:
            sync.flush_all()
        except Exception:
            pass
        _release_single_lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # FastMCP's session manager needs its lifespan inside the parent app
    # (a mounted sub-app lifespan never runs on its own).
    async with _mcp_app.lifespan(app):
        async with _app_lifespan(app):
            yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/mcp", _mcp_app)  # Streamable HTTP: POST /mcp (exact path normalized in middleware)


@app.exception_handler(RequestValidationError)
async def validation_400(req: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": "Invalid request"})


# B15: long-cached shell assets. Immutable only where the URL carries a
# ?v= cache-buster (vendor-cm.js?v=4, manifest.json?v=2, icons, icon.svg?v=3);
# keep ?v in sync on redeploy or a stale bundle lingers in HTTP cache
# (content-hashed filenames = proper fix).
# sw.js is gone (worker dropped 2026-10-03): .js stays no-store for future scripts.
IMMUTABLE_SHELL = frozenset({"vendor-cm.js", "manifest.json", "icon-192.png", "icon-512.png", "icon.svg"})


@app.middleware("http")
async def no_cache_html(req: Request, call: Any):
    if req.url.path == "/mcp":
        req.scope["path"] = "/mcp/"  # agents POST exact /mcp; the mount serves /mcp/*
    if req.url.path.startswith(("/backend", "/data", "/.git", "/tests", "/.github",
                                   "/config.toml", "/.env", "/app.db", "/Dockerfile", "/compose")):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    if req.method in ("POST", "PUT", "DELETE", "PATCH") and not (
            req.url.path == "/mcp" or req.url.path.startswith("/mcp/")):
        o = req.headers.get("origin", "") or req.headers.get("referer", "")
        if o:
            host = (req.headers.get("host", "") or "").split(",")[-1].strip().lower()
            if urlparse(o).netloc.lower() != host:
                log.warning("csrf-block %s", req.url.path)
                return JSONResponse({"detail": "Forbidden"}, status_code=403)
    res = await call(req)
    if req.url.path.rsplit("/", 1)[-1] in IMMUTABLE_SHELL:
        res.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif req.url.path == "/" or req.url.path.endswith((".html", ".js")) or req.url.path.startswith("/api/"):
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
    return {"user": auth.verify_session(token) or name}


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
        try:
            with db.tx() as con:
                empty = con.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0
                ctx = " (first user)" if empty else ""
                if cfg.REGISTRATION == "closed":
                    log.warning("register blocked (closed)%s", ctx)
                    raise HTTPException(403, "Registration disabled")
                elif cfg.REGISTRATION == "invite-only" and not _invite_ok(b.invite, cfg.REGISTRATION_INVITE_TOKEN):
                    if not cfg.REGISTRATION_INVITE_TOKEN:
                        log.warning("register blocked (invite-only, no token configured)%s", ctx)
                        raise HTTPException(403, "Registration disabled: no invite token configured")
                    log.warning("register blocked (invite)%s", ctx)
                    raise HTTPException(403, "Invalid invite code")
                if con.execute("SELECT 1 FROM users WHERE name=? COLLATE NOCASE", (name,)).fetchone():
                    auth.check_password("dummy-timing", auth.DUMMY_HASH)
                    raise HTTPException(400, "Registration failed")
                con.execute("INSERT INTO users (name, hash) VALUES (?,?)", (name, auth.hash_password(b.password)))
                did, now = db.new_id("d_"), db.now_iso()
                con.execute("INSERT INTO docs (id, owner, title, content, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                            (did, name, "Tutorial", TUTORIAL, now, now))
                if empty:
                    log.warning("first user created")
        except sqlite3.IntegrityError as e:
            raise HTTPException(400, "Registration failed") from e
        except sqlite3.OperationalError as e:
            raise busy_503("register", e) from e
    token = auth.mint(name)
    set_cookie(res, req, token)
    return {"user": name}


@app.post("/api/logout")
async def logout(req: Request, res: Response) -> dict:
    limited(req, "auth")
    tok = req.cookies.get(COOKIE, "")
    user = None
    if tok:
        try:
            user = auth.verify_session(tok)
        except Exception:
            user = None
        # Drop cached session first so logged-out tokens die immediately.
        sync.drop_sess_token(tok)
        auth.delete_session(tok)
    if user:
        await sync.kick_all(user)
    clear_cookie(res, req)
    return {"ok": True}


@app.get("/api/me")
def get_me(req: Request, user: str = Depends(me)) -> dict:
    limited(req, "auth")  # own auth bucket: must not share files_list with preview polling
    con = db.connect()
    try:
        r = con.execute("SELECT avatar FROM users WHERE name=?", (user,)).fetchone()
        return {"user": user, "hasAvatar": bool(r and r["avatar"])}
    finally:
        con.close()


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


def me_with_key(req: Request, session: str | None = Cookie(default=None, alias=COOKIE)) -> tuple[str, str]:
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


class KeyCreate(BaseModel):
    name: str = Field(default="", max_length=40, min_length=1)
    role: str = Field(default="editor", max_length=20)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


@app.post("/api/keys")
def create_key(b: KeyCreate, req: Request, authn: tuple[str, str] = Depends(me_with_key)) -> dict:
    user, cap = authn
    limited(req, "keys", user)
    role = b.role.strip().lower()
    if role not in KEY_ROLES:
        raise HTTPException(400, "role must be editor or reviewer")
    if _ROLE_RANK[role] > _ROLE_RANK.get(cap, 0):
        raise HTTPException(403, "Cannot grant more than your own role")
    nm = b.name.strip()[:40]
    if not nm:
        raise HTTPException(400, "Enter a key name.")
    _dc = db.connect()
    try:
        _dup = _dc.execute("SELECT 1 FROM api_keys WHERE username=? AND name=? COLLATE NOCASE AND revoked=0",
                           (user, nm)).fetchone()
    finally:
        _dc.close()
    if _dup:
        raise HTTPException(400, "Key name already used")
    expires_at = (datetime.now(UTC) + timedelta(days=b.expires_in_days)).isoformat() if b.expires_in_days else ""
    for _ in range(2):  # hash collision retry (practically impossible, fail-closed)
        kid, full, prefix = mint_api_key()
        con = db.connect()
        try:
            try:
                con.execute("INSERT INTO api_keys (id, username, name, prefix, key_hash, role, expires_at, created_at) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            (kid, user, nm, prefix, auth.sha(full), role, expires_at, db.now_iso()))
                con.commit()
            except sqlite3.IntegrityError:
                continue
            return {"id": kid, "name": nm, "prefix": prefix,
                    "key": full, "role": role, "expires_at": expires_at}
        finally:
            con.close()
    raise HTTPException(500, "Key creation failed")


@app.get("/api/keys")
def list_keys(req: Request, authn: tuple[str, str] = Depends(me_with_key)) -> dict:
    user, _cap = authn
    limited(req, "keys", user)
    con = db.connect()
    try:
        rows = con.execute("SELECT id, name, prefix, role, expires_at, last_used, created_at FROM api_keys "
                           "WHERE username=? AND revoked=0 ORDER BY created_at", (user,)).fetchall()
        return {"keys": [dict(r) for r in rows]}
    finally:
        con.close()


@app.delete("/api/keys/{kid}")
def revoke_key(kid: str, req: Request, authn: tuple[str, str] = Depends(me_with_key)) -> dict:
    user, _cap = authn
    limited(req, "keys", user)
    con = db.connect()
    try:
        cur = con.execute("UPDATE api_keys SET revoked=1 WHERE id=? AND username=? AND revoked=0", (kid, user))
        con.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "Key gone")
        return {"ok": True}
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
async def change_password(b: PwChange, req: Request, res: Response, user: str = Depends(me)) -> dict:
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
async def rename_me(b: NameChange, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "pw")
    new = b.name.strip()
    if not re.fullmatch(NAME_RE, new):
        raise HTTPException(400, "Name: 2-20 chars, letters/numbers/_-")
    check_pw(user, b.password)
    if new == user:
        return {"user": user}
    # No ON UPDATE CASCADE in schema.sql (adding it needs a real migration,
    # FKs are bare REFERENCES): rename stays an explicit 7-table move inside
    # one transaction. Pre-check message is generic (no user enumeration).
    con = db.connect()
    try:
        if new.lower() != user.lower() and con.execute("SELECT 1 FROM users WHERE name=? COLLATE NOCASE", (new,)).fetchone():
            raise HTTPException(400, "Rename failed")
        row = con.execute("SELECT hash, avatar FROM users WHERE name=?", (user,)).fetchone()
        if not row:
            raise HTTPException(404, "User gone")
    finally:
        con.close()
    try:
        with db.tx() as con:
            _dup = con.execute("SELECT name FROM users WHERE name=? COLLATE NOCASE", (new,)).fetchone()
            if _dup and _dup["name"].lower() != user.lower():
                raise HTTPException(400, "Rename failed")
            con.execute("INSERT INTO users (name, hash, avatar) VALUES (?,?,?)",
                        (new, row["hash"], row["avatar"]))
            con.execute("UPDATE sessions SET username=? WHERE username=?", (new, user))
            con.execute("UPDATE docs SET owner=? WHERE owner=?", (new, user))
            con.execute("UPDATE shares SET username=? WHERE username=?", (new, user))
            con.execute("UPDATE comments SET username=? WHERE username=?", (new, user))
            con.execute("UPDATE templates SET owner=? WHERE owner=?", (new, user))
            con.execute("UPDATE folders SET owner=? WHERE owner=?", (new, user))
            con.execute("UPDATE api_keys SET username=? WHERE username=?", (new, user))
            con.execute("DELETE FROM users WHERE name=?", (user,))
    except sqlite3.OperationalError as e:
        log.warning("rename_me %s -> %s busy: %s", user, new, e)
        raise HTTPException(503, "Database busy, try again") from e
    except sqlite3.IntegrityError as e:
        log.warning("rename_me %s -> %s failed: %s", user, new, e)
        raise HTTPException(400, "Rename failed") from e
    await sync.kick_all(user)
    await sync.kick_all(new)
    sync.drop_role_cache(user)
    sync.drop_role_cache(new)
    sync.drop_sess_cache(user)
    sync.drop_sess_cache(new)
    _drop_user_locks(user)
    return {"user": new}


@app.post("/api/me/avatar")
def set_avatar(b: AvatarSet, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "avatar")
    m = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", b.img)
    if not m or len(b.img) > 200_000:
        raise HTTPException(400, "Only PNG/JPEG/WebP as data URL (max 200 KB)")
    new_val = m.group(1) + ":" + m.group(2)
    _c = db.connect()
    try:
        old = _c.execute("SELECT avatar FROM users WHERE name=?", (user,)).fetchone()
        old_val = old["avatar"] if old and old["avatar"] else ""
    finally:
        _c.close()

    def _restore_avatar() -> None:
        _rb = db.connect()
        try:
            _rb.execute("UPDATE users SET avatar=? WHERE name=?", (old_val, user))
            _rb.commit()
        finally:
            _rb.close()

    try:
        with quota_svc.quota_guard(user, max(0, len(b.img.encode("utf-8")) - len(old_val.encode("utf-8"))),
                                   rollback=_restore_avatar):
            con = db.connect()
            try:
                con.execute("UPDATE users SET avatar=? WHERE name=?", (new_val, user))
                con.commit()
            finally:
                con.close()
    except sqlite3.OperationalError as e:
        raise busy_503("set_avatar", e) from e
    return {"ok": True}


@app.delete("/api/me/avatar")
def del_avatar(req: Request, user: str = Depends(me)) -> dict:
    limited(req, "avatar")
    con = db.connect()
    try:
        con.execute("UPDATE users SET avatar='' WHERE name=?", (user,))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@app.get("/api/avatar/{username}")
def get_avatar(username: str, req: Request, user: str = Depends(me)) -> Response:
    limited(req, "files_list")
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
            raise HTTPException(404, "No image") from None
        return Response(content=raw, media_type=mime,
                        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"}) # busted via ?v=, no limit needed
    finally:
        con.close()


@app.post("/api/me/delete")
async def delete_me(b: PwOnly, req: Request, res: Response, user: str = Depends(me)) -> dict:
    limited(req, "pw")
    check_pw(user, b.password)
    con = db.connect()
    try:
        owned = [r["id"] for r in con.execute("SELECT id FROM docs WHERE owner=?", (user,)).fetchall()]
    finally:
        con.close()
    # Files first: trash-rename aside so a crash between FS and DB never loses
    # data (DB still points at the doc, files restorable from .trash-<id>).
    trashed_dirs: list[tuple[Path, Path]] = []
    for did in owned:
        src = get_files_dir() / did
        if src.is_dir():
            dst = get_files_dir() / f".trash-{did}"
            try:
                if dst.exists():
                    shutil.rmtree(dst, ignore_errors=True)
                src.rename(dst)
                trashed_dirs.append((src, dst))
            except OSError as e:
                log.warning("delete_me %s: trash-rename failed: %s", did, e)
    try:
        with db.tx() as con:
            con.execute("DELETE FROM comments WHERE username=? AND parent_id IS NOT NULL", (user,))
            con.execute("UPDATE comments SET username='[deleted]', author='' WHERE username=?", (user,))
            con.execute("DELETE FROM users WHERE name=?", (user,))
    except sqlite3.OperationalError as e:
        # DB delete failed: move files back, account still intact.
        for src, dst in trashed_dirs:
            try:
                dst.rename(src)
            except OSError:
                pass
        raise busy_503("delete_me", e) from e
    for did in owned:
        await sync.drop(did)
    for _src, dst in trashed_dirs:
        try:
            shutil.rmtree(dst, ignore_errors=True)
        except OSError:
            log.warning("delete_me %s: rmtree failed", dst.name)
    await sync.kick_all(user)
    _drop_user_locks(user)
    if req.cookies.get(COOKIE):
        auth.delete_session(req.cookies[COOKIE])
    clear_cookie(res, req)
    return {"ok": True}


@app.websocket("/ws/{doc_id}")
async def ws_doc(ws: WebSocket, doc_id: str) -> None:
    try:
        check_doc_id(doc_id)
    except HTTPException:
        await ws.accept()
        await ws.close(code=4403)
        return
    await sync.handle(ws, doc_id)


@app.get("/api/docs")
def list_docs(req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files_list")
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


@app.get("/api/folders")
def list_folders(req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files_list")
    con = db.connect()
    try:
        return {"folders": _folder_counts(con, user, "doc")}
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
def make_folder(b: FolderSet, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "folders")
    n = check_folder_name(b.folder)
    con = db.connect()
    try:
        ensure_folder(con, user, "doc", n)
        con.commit()
        notify_sidebar(user)
        return {"folder": n}
    finally:
        con.close()


@app.post("/api/docs/create")
def create_doc(b: DocCreate, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "create")
    t = b.title.strip()
    if not t or len(t) > TITLE_MAX:
        raise HTTPException(400, f"Title: 1-{TITLE_MAX} chars")
    if len(b.content) > MAX_TXT:
        raise HTTPException(400, "Doc too large (max 200 KB)")
    try:
        check_quota(user, len(b.content.encode("utf-8")))
    except sqlite3.OperationalError as e:
        raise busy_503("create_doc", e) from e
    try:
        max_docs = config.load().MAX_DOCS_PER_USER
    except Exception:
        max_docs = 100
    did, now = db.new_id("d_"), db.now_iso()
    try:
        with db.tx() as con:
            if con.execute("SELECT COUNT(*) AS n FROM docs WHERE owner=?", (user,)).fetchone()["n"] >= max_docs:
                raise HTTPException(400, "Too many docs")
            con.execute("INSERT INTO docs (id, owner, title, content, folder, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (did, user, t, b.content,
                         b.folder.strip()[:FOLDER_MAX], now, now))
            ensure_folder(con, user, "doc", b.folder)
    except sqlite3.IntegrityError as e:
        raise HTTPException(400, "Title already exists") from e
    except sqlite3.OperationalError as e:
        raise busy_503("create_doc", e) from e
    notify_sidebar(user)
    return {"id": did}


@app.get("/api/docs/{doc_id}")
def get_doc(doc_id: str, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files_list")
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
        except sqlite3.OperationalError as e:
            log.warning("auto_snap %s busy, skipped: %s", doc_id, e)
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
        except sqlite3.OperationalError as e:
            log.warning("auto_snap %s failed: %s", doc_id, e)
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/save")
async def save_doc(doc_id: str, b: DocSave, req: Request, user: str = Depends(me)) -> dict:
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
        finally:
            _c.close()
    except sqlite3.OperationalError as e:
        raise busy_503("save_doc", e) from e
    _old_text = (_old["content"] or "") if _old else ""
    _old_len = len(_old_text.encode("utf-8"))
    _save_owner = _owner(doc_id, user)

    def _restore_old() -> None:
        _rb = db.connect()
        try:
            _rb.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?",
                        (_old_text, db.now_iso(), doc_id))
            _rb.commit()
        finally:
            _rb.close()

    try:
        with quota_svc.quota_guard(_save_owner, max(0, len(content.encode("utf-8")) - _old_len),
                                   rollback=_restore_old):
            try:
                with db.tx() as con:
                    trashed = con.execute("SELECT trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
                    if not trashed:
                        raise HTTPException(404, "Doc gone")
                    if trashed["trashed"]:
                        raise HTTPException(410, "In trash - restore first")
                    if need_access(user, doc_id) not in ("owner", "editor"):
                        raise HTTPException(403, "Reviewer can only comment")
                    con.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?",
                                (content, db.now_iso(), doc_id))
            except sqlite3.OperationalError as e:
                raise busy_503("save_doc", e) from e
    except sqlite3.OperationalError as e:
        raise busy_503("save_doc", e) from e
    except HTTPException as e:
        if e.status_code == 413 and live is not None:
            await sync.replace_text(doc_id, _old_text)
        raise
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
def rename_doc(doc_id: str, b: TitleSet, req: Request, user: str = Depends(me)) -> dict:
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
        notify_sidebar(user)
        return {"ok": True}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Title already exists") from None
    finally:
        con.close()


@app.get("/api/templates")
def list_templates(req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files_list")
    con = db.connect()
    try:
        rows = con.execute("SELECT name, content, line, folder FROM templates WHERE owner=? ORDER BY name",
                           (user,)).fetchall()
        return {"templates": [dict(r) for r in rows]}
    finally:
        con.close()


@app.post("/api/templates")
def save_template(b: TplSave, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "save")  # reuse save scope (no dedicated template scope)
    n = re.sub(r"[^A-Za-z0-9._-]", "_", Path(b.name or "").name.strip().lstrip("."))[:100]
    if not n.endswith(".typ") or not b.content.strip() or len(b.content) > MAX_TXT:
        raise HTTPException(400, "Only .typ with content (max 200 KB)")
    try:
        _c = db.connect()
        try:
            _old = _c.execute("SELECT content, folder FROM templates WHERE owner=? AND name=?", (user, n)).fetchone()
        finally:
            _c.close()
    except sqlite3.OperationalError as e:
        raise busy_503("save_template", e) from e
    _old_tpl = (_old["content"] or "") if _old else ""
    _old_tpl_len = len(_old_tpl.encode("utf-8"))

    def _restore_tpl() -> None:
        _rb = db.connect()
        try:
            if _old is None:
                _rb.execute("DELETE FROM templates WHERE owner=? AND name=?", (user, n))
            else:
                _rb.execute("UPDATE templates SET content=?, updated_at=? WHERE owner=? AND name=?",
                            (_old_tpl, db.now_iso(), user, n))
            _rb.commit()
        finally:
            _rb.close()

    try:
        with quota_svc.quota_guard(user, max(0, len(b.content.encode("utf-8")) - _old_tpl_len),
                                   rollback=_restore_tpl):
            con = db.connect()
            try:
                con.execute("INSERT INTO templates (owner, name, content, line, folder, updated_at) VALUES (?,?,?,?,?,?) "
                            "ON CONFLICT (owner, name) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at",
                            (user, n, b.content, f'#include "{n}"', b.folder.strip()[:FOLDER_MAX], db.now_iso()))
                ensure_folder(con, user, "tpl", b.folder)
                con.commit()
            finally:
                con.close()
    except sqlite3.OperationalError as e:
        raise busy_503("save_template", e) from e
    if _old is None or (_old["folder"] or "") != b.folder.strip()[:FOLDER_MAX]:
        notify_sidebar(user)  # content-only updates don't change the list
    return {"name": n}


@app.delete("/api/templates/{name}")
def delete_template(name: str, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files")  # reuse files scope (no dedicated template scope)
    n = tpl_name(name)
    con = db.connect()
    try:
        cur = con.execute("DELETE FROM templates WHERE owner=? AND name=?", (user, n))
        con.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "Template gone")
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/templates/{name}/folder")
def move_template(name: str, b: FolderSet, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files")  # reuse files scope (no dedicated template scope)
    n = tpl_name(name)
    con = db.connect()
    try:
        cur = con.execute("UPDATE templates SET folder=?, updated_at=? WHERE owner=? AND name=?",
                    (b.folder.strip()[:FOLDER_MAX], db.now_iso(), user, n))
        ensure_folder(con, user, "tpl", b.folder)
        con.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "Template gone")
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@app.get("/api/tplfolders")
def list_tpl_folders(req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files_list")
    con = db.connect()
    try:
        return {"folders": _folder_counts(con, user, "tpl")}
    finally:
        con.close()


@app.post("/api/tplfolders")
def make_tpl_folder(b: FolderSet, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "folders")
    n = check_folder_name(b.folder)
    con = db.connect()
    try:
        ensure_folder(con, user, "tpl", n)
        con.commit()
        notify_sidebar(user)
        return {"folder": n}
    finally:
        con.close()


@app.post("/api/tplfolders/rename")
def rename_tpl_folder(b: FolderRename, req: Request, user: str = Depends(me)) -> dict:
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
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@app.delete("/api/tplfolders/{name}")
def drop_tpl_folder(name: str, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files")  # reuse files scope (no dedicated template scope)
    n = name.strip()[:FOLDER_MAX]
    con = db.connect()
    try:
        con.execute("UPDATE templates SET folder='' WHERE owner=? AND folder=?", (user, n))
        con.execute("DELETE FROM folders WHERE owner=? AND kind='tpl' AND name=?", (user, n))
        con.commit()
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@app.delete("/api/docs/{doc_id}")
async def delete_doc(doc_id: str, req: Request, user: str = Depends(me)) -> dict:
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
            notify_sidebar(user)
            return {"trashed": True}
        con.execute("DELETE FROM docs WHERE id=?", (doc_id,))
        con.commit()
    finally:
        con.close()
    await sync.drop(doc_id)
    _drop_doc_locks(doc_id)
    notify_sidebar(user)
    try:
        shutil.rmtree(get_files_dir() / doc_id, ignore_errors=True)
    except OSError:
        log.warning("delete_doc %s: rmtree failed", doc_id)
    return {"trashed": False}


@app.post("/api/docs/{doc_id}/restore")
def restore_doc(doc_id: str, req: Request, user: str = Depends(me)) -> dict:
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
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/folder")
def move_doc(doc_id: str, b: FolderSet, req: Request, user: str = Depends(me)) -> dict:
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
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@app.delete("/api/folders/{name}")
def drop_folder(name: str, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "folders")
    n = name.strip()[:FOLDER_MAX]
    con = db.connect()
    try:
        con.execute("UPDATE docs SET folder='' WHERE owner=? AND folder=? AND trashed=0", (user, n))
        con.execute("DELETE FROM folders WHERE owner=? AND kind='doc' AND name=?", (user, n))
        con.commit()
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/folders/rename")
def rename_folder(b: FolderRename, req: Request, user: str = Depends(me)) -> dict:
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
        notify_sidebar(user)
        return {"ok": True}
    finally:
        con.close()


@app.post("/api/docs/{doc_id}/duplicate")
def duplicate_doc(doc_id: str, req: Request, user: str = Depends(me)) -> dict:
    check_doc_id(doc_id)
    limited(req, "duplicate")
    need_edit(user, doc_id)
    try:
        max_docs = config.load().MAX_DOCS_PER_USER
    except Exception:
        max_docs = 100
    nid, now = db.new_id("d_"), db.now_iso()
    src = get_files_dir() / doc_id
    with _doc_lock(f"dup:{user}"):
        try:
            with db.tx() as con:
                if con.execute("SELECT COUNT(*) AS n FROM docs WHERE owner=?", (user,)).fetchone()["n"] >= max_docs:
                    raise HTTPException(400, "Too many docs")
                d = con.execute("SELECT title, content, folder, trashed FROM docs WHERE id=?",
                                (doc_id,)).fetchone()
                if not d:
                    raise HTTPException(404, "Doc gone")
                if d["trashed"]:
                    raise HTTPException(410, "In trash - restore first")
                base = d["title"] + " (copy)"
                title, i = base, 2
                while con.execute("SELECT 1 FROM docs WHERE owner=? AND title=? COLLATE NOCASE",
                                  (user, title)).fetchone():
                    title, i = f"{base} {i}", i + 1
                    if i > 99:
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
                    raise HTTPException(400, "Too many files")
                fbytes = 0
                for p in files:
                    try:
                        fbytes += p.stat().st_size
                    except OSError:
                        pass
                check_quota(user, len(text.encode("utf-8")) + fbytes)
                con.execute("INSERT INTO docs (id, owner, title, content, folder, created_at, updated_at) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (nid, user, title, text, d["folder"], now, now))
        except sqlite3.IntegrityError as e:
            raise HTTPException(400, "Title already exists") from e
        except sqlite3.OperationalError as e:
            raise busy_503("duplicate_doc", e) from e
    if src.is_dir():
        try:
            shutil.copytree(src, get_files_dir() / nid, ignore=shutil.ignore_patterns(".*", "*.tmp.*"), dirs_exist_ok=True)
        except (OSError, shutil.Error) as e:
            log.warning("duplicate %s -> %s: copytree failed: %s", doc_id, nid, e)
            try:
                shutil.rmtree(get_files_dir() / nid, ignore_errors=True)
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
            raise HTTPException(500, "Copy failed") from None
    notify_sidebar(user)
    return {"id": nid}


@app.post("/api/docs/{doc_id}/share")
async def share_doc(doc_id: str, b: Share, req: Request, user: str = Depends(me)) -> dict:
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
    notify_sidebar(b.username)  # sharee's list changed
    return {"ok": True}


@app.delete("/api/docs/{doc_id}/share/{username}")
async def unshare_doc(doc_id: str, username: str, req: Request, user: str = Depends(me)) -> dict:
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
    notify_sidebar(username)  # ex-sharee's list changed
    return {"ok": True}


@app.get("/api/docs/{doc_id}/comments")
def list_comments(doc_id: str, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files_list")
    check_doc_id(doc_id)
    need_access(user, doc_id)
    con = db.connect()
    try:
        rows = con.execute("SELECT id, username, author, anchor, quote, text, parent_id, resolved, created_at FROM comments "
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
def add_comment(doc_id: str, b: CommentNew, req: Request, user: str = Depends(me)) -> dict:
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
        q = b.quote[:500]
        con.execute("INSERT INTO comments (id, doc_id, username, author, anchor, quote, text, parent_id, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (cid, doc_id, user, "", b.anchor, q if q.strip() else "", b.text.strip(), b.parent_id, db.now_iso()))
        con.commit()
        return {"id": cid}
    finally:
        con.close()


@app.delete("/api/docs/{doc_id}/comments/{cid}")
def delete_comment(doc_id: str, cid: str, req: Request, user: str = Depends(me)) -> dict:
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
def move_comment(doc_id: str, cid: str, b: AnchorSet, req: Request, user: str = Depends(me)) -> dict:
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
def edit_comment(doc_id: str, cid: str, b: CommentEdit, req: Request, user: str = Depends(me)) -> dict:
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
def resolve_comment(doc_id: str, cid: str, b: ResolveSet, req: Request, user: str = Depends(me)) -> dict:
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
    if ".tmp." in n:
        raise HTTPException(400, "Reserved name")
    return n


def tpl_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name or "").name.strip().lstrip("."))[:100]
    if not n.endswith(".typ"):
        raise HTTPException(404, "Template gone")
    return n


DOC_ID_RE = re.compile(r"^d_[A-Za-z0-9_-]+$")


def check_doc_id(doc_id: str) -> None:
    if not DOC_ID_RE.fullmatch(doc_id or ""):
        raise HTTPException(404, "Document not found")


@app.get("/api/docs/{doc_id}/files")
def list_files(doc_id: str, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files_list") # own bucket: preview polls this per render, must not starve uploads
    check_doc_id(doc_id)
    need_access(user, doc_id)
    d = get_files_dir() / doc_id
    out = []
    if d.is_dir():
        try:
            entries = sorted(d.iterdir())
        except OSError as e:
            log.warning("list_files list failed: %s", e)
            raise HTTPException(500, "File list failed") from e
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
def upload_file(doc_id: str, f: UploadFile, req: Request, user: str = Depends(me)) -> dict:
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
    d = get_files_dir() / doc_id
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.warning("upload_file mkdir failed: %s", e)
        raise HTTPException(500, "Upload failed") from e
    try:
        pre = sum(1 for p in d.iterdir() if p.is_file() and p.name != n and ".tmp." not in p.name)
    except OSError as e:
        log.warning("upload_file list failed: %s", e)
        raise HTTPException(500, "File list failed") from e
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
        raise HTTPException(500, "Upload failed") from e
    try:
        old = (d / n).read_bytes() if (d / n).is_file() else None
    except OSError:
        old = None

    def _restore_upload() -> None:
        try:
            if old is not None:
                (d / n).write_bytes(old)
            else:
                (d / n).unlink(missing_ok=True)
        except OSError:
            pass

    _up_owner = _owner(doc_id, user)
    try:
        with quota_svc.quota_guard(_up_owner, max(0, size - (len(old) if old is not None else 0)), rollback=_restore_upload):
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
                raise HTTPException(500, "File list failed") from e
            if post > max_files:
                _restore_upload()
                raise HTTPException(400, "Too many files")
    except sqlite3.OperationalError as e:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise busy_503("upload_file", e) from e
    except HTTPException:
        # Both 413 paths clean up tmp (pre-check never replaced it, post-check rolls back).
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    touch_doc(doc_id)
    return {"name": n, "size": size}


@app.get("/api/docs/{doc_id}/files/{name}")
def get_file(doc_id: str, name: str, req: Request, user: str = Depends(me)) -> Response:
    limited(req, "files")
    check_doc_id(doc_id)
    need_access(user, doc_id)
    p = get_files_dir() / doc_id / safe_name(name)
    if not p.is_file():
        raise HTTPException(404, "File gone")
    if p.suffix.lower() == ".svg":
        try:
            data = p.read_bytes()
        except OSError as e:
            log.warning("get_file gone %s: %s", p.name, e)
            raise HTTPException(404, "File gone") from e
        return Response(content=data, media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{p.name}"',
                                 "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
    try:
        return FileResponse(str(p), filename=p.name,
                            headers={"Content-Disposition": f'attachment; filename="{p.name}"',
                                     "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
    except (FileNotFoundError, RuntimeError, OSError) as e:
        log.warning("get_file gone %s: %s", p.name, e)
        raise HTTPException(404, "File gone") from e


@app.delete("/api/docs/{doc_id}/files/{name}")
def delete_file(doc_id: str, name: str, req: Request, user: str = Depends(me)) -> dict:
    check_doc_id(doc_id)
    limited(req, "files")
    need_edit(user, doc_id)
    with _doc_lock(f"upload:{doc_id}"):
        p = get_files_dir() / doc_id / safe_name(name)
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
            raise busy_503("touch_doc", e) from e
    finally:
        con.close()


@app.get("/api/docs/{doc_id}/files/{name}/text")
def get_file_text(doc_id: str, name: str, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "save") # same cadence as doc save, not the tight files bucket
    check_doc_id(doc_id)
    need_access(user, doc_id)
    p = get_files_dir() / doc_id / need_text(name)
    if not p.is_file():
        raise HTTPException(404, "File gone")
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        log.warning("get_file_text gone %s: %s", p.name, e)
        raise HTTPException(404, "File gone") from e
    return {"name": p.name, "content": content}


@app.post("/api/docs/{doc_id}/files/{name}/text")
def save_file_text(doc_id: str, name: str, b: FileText, req: Request, user: str = Depends(me)) -> dict:
    check_doc_id(doc_id)
    limited(req, "save") # autosave every SAVE_MS, like doc save (files bucket is for up/download)
    need_edit(user, doc_id)
    if len(b.content) > MAX_TXT:
        raise HTTPException(400, "Max 200 KB")
    with _doc_lock(f"upload:{doc_id}"):
        p = get_files_dir() / doc_id / need_text(name)
        try:
            _old_sz = p.stat().st_size if p.is_file() else 0
        except OSError:
            _old_sz = 0
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.warning("save_file_text mkdir failed: %s", e)
            raise HTTPException(500, "Upload failed") from e
        try:
            old = p.read_bytes() if p.is_file() else None
        except OSError:
            old = None

        def _restore_text() -> None:
            try:
                if old is None:
                    p.unlink(missing_ok=True)
                else:
                    p.write_bytes(old)
            except OSError:
                pass

        tmp = p.parent / f"{p.name}.tmp.{secrets.token_hex(8)}"
        try:
            with quota_svc.quota_guard(_owner(doc_id, user),
                                       max(0, len(b.content.encode("utf-8")) - _old_sz),
                                       rollback=_restore_text):
                try:
                    tmp.write_text(b.content, encoding="utf-8")
                    os.replace(tmp, p)
                except OSError:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise
        except sqlite3.OperationalError as e:
            raise busy_503("save_file_text", e) from e
        touch_doc(doc_id)
    return {"ok": True}


@app.post("/api/docs/{doc_id}/invite")
def make_invite(doc_id: str, b: InviteNew, req: Request, user: str = Depends(me)) -> dict:
    check_doc_id(doc_id)
    limited(req, "invite")
    if need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can invite")
    if b.role not in ("editor", "reviewer"):
        raise HTTPException(400, "role must be editor or reviewer")
    tok = db.new_id("")
    # hint is an independent random id for listing/deleting invites: it must
    # NOT derive from the token (tok[:8] would leak 48 bits and help guessing).
    hint = secrets.token_hex(4)
    con = db.connect()
    try:
        cut = (datetime.now(UTC) - timedelta(seconds=INVITE_SECONDS)).isoformat()
        if con.execute("SELECT COUNT(*) AS n FROM invites WHERE doc_id=? AND created_at>?",
                       (doc_id, cut)).fetchone()["n"] >= 20:
            raise HTTPException(400, "Too many invites")
        con.execute("INSERT INTO invites (token, doc_id, role, hint, created_at) VALUES (?,?,?,?,?)",
                    (auth.sha(tok), doc_id, b.role, hint, db.now_iso()))
        con.commit()
        # Link invites are intentionally multi-use: redeeming does NOT delete
        # the invite (see _redeem_invite); owners revoke via DELETE invites.
        return {"token": tok}
    finally:
        con.close()


@app.get("/api/docs/{doc_id}/invites")
def list_invites(doc_id: str, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files_list")
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
def drop_invite(doc_id: str, hint: str, req: Request, user: str = Depends(me)) -> dict:
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
def join_doc(token: str, req: Request, user: str = Depends(me)) -> dict:
    raise HTTPException(410, "Use POST /api/join with body")


@app.post("/api/join")
def join_doc_body(b: JoinBody, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "join")
    return _redeem_invite(b.token.strip(), user)


def _redeem_invite(token: str, user: str) -> dict:
    # Link invites are intentionally multi-use (no delete after redeem):
    # anyone with the link joins; only expiry or owner revoke invalidates.
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
            notify_sidebar(user)  # joiner's shared list changed
        return {"id": inv["doc_id"]}
    finally:
        con.close()


@app.get("/api/docs/{doc_id}/snapshots")
def list_snaps(doc_id: str, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files_list")
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
def make_snap(doc_id: str, b: SnapNew, req: Request, user: str = Depends(me)) -> dict:
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
def get_snap(doc_id: str, sid: str, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files_list")
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
                       force: bool = False, b: SnapRestore | None = None) -> dict:
    check_doc_id(doc_id)
    limited(req, "snapshots")
    need_edit(user, doc_id)
    eff = force or (b.force if b else False)  # query or body flag, default safe
    auto = sync.room_text(doc_id)
    try:
        with db.tx() as con:
            s = con.execute("SELECT content FROM snapshots WHERE id=? AND doc_id=?", (sid, doc_id)).fetchone()
            if not s:
                raise HTTPException(404, "Snapshot gone")
            cur = con.execute("SELECT content, trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
            if not cur:
                raise HTTPException(404, "Doc gone")
            if cur["trashed"]:
                raise HTTPException(410, "In trash - restore first")
            if auto is not None and auto != (cur["content"] or "") and not eff:
                raise HTTPException(409, "Document changed meanwhile, retry with force")
            before = auto if auto is not None else cur["content"]
            check_quota(_owner(doc_id, user), max(0, len((s["content"] or "").encode("utf-8")) - len((cur["content"] or "").encode("utf-8"))))
            con.execute("INSERT INTO snapshots (id, doc_id, content, label, created_at) VALUES (?,?,?,?,?)",
                        (db.new_id("s_"), doc_id, before, "Before restore", db.now_iso()))
            prune_snaps(con, doc_id)
            con.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?", (s["content"], db.now_iso(), doc_id))
    except sqlite3.OperationalError as e:
        raise busy_503("restore_snap", e) from e
    await sync.replace_text(doc_id, s["content"])
    return {"ok": True}


@app.delete("/api/docs/{doc_id}/snapshots/{sid}")
def delete_snap(doc_id: str, sid: str, req: Request, user: str = Depends(me)) -> dict:
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
def list_members(doc_id: str, req: Request, user: str = Depends(me)) -> dict:
    limited(req, "files_list")
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
def search_docs(req: Request, q: str = "", user: str = Depends(me)) -> dict:
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


def zip_name(s: str) -> str:
    n = re.sub(r"[^A-Za-z0-9_.-]+", "_", s.strip())[:80].strip("._") or "document"
    return n


def prune_old_exports(max_age_s: int = 86400) -> None:
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
    except OSError as e:
        logging.getLogger(__name__).warning("prune exports failed: %s", e)


@app.get("/api/export.zip")
def export_zip(req: Request, background: BackgroundTasks, user: str = Depends(me)) -> Response:
    limited(req, "export")
    o = req.headers.get("origin", "") or req.headers.get("referer", "")
    if o:
        host = (req.headers.get("host", "") or "").split(",")[-1].strip().lower()
        if urlparse(o).netloc.lower() != host:
            log.warning("csrf-block %s", req.url.path)
            raise HTTPException(403, "Forbidden")
    # Defense in depth for this cookie-authed download: a cross-site top-level
    # navigation cannot carry the session usefully, so reject it when the
    # browser tells us where the request comes from. Only enforced when the
    # header is present (curl/TestClient send none).
    sfs = (req.headers.get("sec-fetch-site", "") or "").strip().lower()
    if sfs and sfs not in ("same-origin", "same-site", "none"):
        log.warning("csrf-block %s (sec-fetch-site=%s)", req.url.path, sfs)
        raise HTTPException(403, "Forbidden")
    lock = _export_lock(user)
    if not lock.acquire(blocking=False):
        raise HTTPException(429, "Export already running")
    try:
        return _export_zip(req, background, user)
    finally:
        lock.release()


def _export_zip(req: Request, background: BackgroundTasks, user: str) -> Response:
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
        fdir = get_files_dir() / d["id"]
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
    get_files_dir().parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, dir=get_files_dir().parent, suffix=".zip")
        tmp.close()
    except OSError as e:
        log.warning("export tmp failed: %s", e)
        raise HTTPException(503, "Export busy, try again") from e
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
                fdir = get_files_dir() / d["id"]
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


@app.get("/api/events")
async def sidebar_events(req: Request, user: str = Depends(me)):
    limited(req, "files_list")  # like other list reads; churn-reconnects still count
    if len(_SIDEBAR_Q.get(user, ())) >= 5:
        raise HTTPException(429, "Too many streams")
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    entry = (loop, q)
    _SIDEBAR_Q.setdefault(user, set()).add(entry)

    async def _gen():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"event: {msg}\ndata: 1\n\n"
                except TimeoutError:
                    if not auth.verify_session(req.cookies.get(COOKIE, "")):
                        break  # logged out/expired/revoked mid-stream: stop, client reconnects on next login
                    yield ": ping\n\n"  # keep proxies from closing idle streams
        finally:
            _left = _SIDEBAR_Q.get(user, set())
            _left.discard(entry)
            if not _left:
                _SIDEBAR_Q.pop(user, None)

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def api_fallback(full_path: str) -> dict:
    raise HTTPException(404, "API gone")


@app.get("/healthz", response_model=None)
def healthz() -> dict | Response:
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


FRONT_FILES = IMMUTABLE_SHELL  # one asset set: served files = immutable-cache files


@app.get("/")
def frontend_root() -> FileResponse:
    try:
        return FileResponse(str(ROOT / "index.html"))
    except (FileNotFoundError, RuntimeError, OSError):
        raise HTTPException(404, "Not found") from None


@app.get("/{name}")
def frontend_file(name: str) -> FileResponse:
    if name in FRONT_FILES:
        p = ROOT / name
        if p.is_file():
            try:
                return FileResponse(str(p))
            except (FileNotFoundError, RuntimeError, OSError):
                pass
    raise HTTPException(404, "Not found")
