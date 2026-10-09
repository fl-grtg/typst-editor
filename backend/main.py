from __future__ import annotations

import logging
import sqlite3
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend import config, db, deps, sync

# Backwards-compatible names: older tests and tooling import these from
# backend.main. New code should import from the owning module.
from backend.constants import EXPORT_MAX  # noqa: F401
from backend.deps import check_quota, get_files_dir, user_bytes  # noqa: F401
from backend.mcp_server import mcp_http_app as _mcp_app
from backend.routers import (
    auth,
    comments,
    docs,
    events,
    export,
    files,
    frontend,
    share,
    snapshots,
    system,
    templates,
    ws,
)
from backend.routers.auth import _cookie_secure  # noqa: F401
from backend.routers.export import prune_old_exports  # noqa: F401
from backend.routers.frontend import FRONT_FILES  # noqa: F401
from backend.services.locks import (  # noqa: F401
    _DOC_LOCKS,
    _DOC_LOCKS_GUARD,
    _EXPORT_LOCKS,
    _acquire_single_lock,
    _export_lock,
    _named_lock,
    _release_single_lock,
)
from backend.services.maintenance import reap_trash_dirs
from backend.services.proxy import _proxy_peer_allowed, _proxy_startup_check, _proxy_trusted, client_ip  # noqa: F401
from backend.services.sidebar import _SIDEBAR_Q  # noqa: F401

log = logging.getLogger("typst.main")


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
        # C10: refuse TRUST_PROXY=true with an open FORWARDED_ALLOW_IPS.
        # SystemExit (BaseException) propagates through the except below.
        _proxy_startup_check(_cfg)
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
    if req.url.path.rsplit("/", 1)[-1] in deps.IMMUTABLE_SHELL:
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
        if _proxy_trusted(req):
            fwd_proto = (req.headers.get("x-forwarded-proto", "") or "").split(",")[-1].strip().lower()
    except Exception:
        pass
    if proto == "https" or fwd_proto == "https":
        res.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    res.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return res


@app.exception_handler(sqlite3.OperationalError)
async def sqlite_busy_handler(req: Request, exc: sqlite3.OperationalError) -> JSONResponse:
    # single place instead of 20 try-blocks: locked/busy -> 503, rest -> 500
    msg = str(exc).lower()
    if "locked" in msg or "busy" in msg:
        e = deps.busy_503("db", exc)
        return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
    log.warning("db operational: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Database error"})


# Route registration. Order matters only for the catch-alls: the API fallback
# (in `system`) must come after every /api route and the static frontend last.
app.include_router(ws.router)
app.include_router(auth.router)
app.include_router(docs.router)
app.include_router(templates.router)
app.include_router(share.router)
app.include_router(comments.router)
app.include_router(files.router)
app.include_router(snapshots.router)
app.include_router(export.router)
app.include_router(events.router)
app.include_router(system.router)
app.include_router(frontend.router)
