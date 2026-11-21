"""OpenID Connect login and auth discovery endpoints."""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from backend import auth, config, deps, sync
from backend.routers.auth import _cookie_secure, set_cookie
from backend.services import oidc as oidc_svc

log = logging.getLogger("typst.main")

router = APIRouter()


@router.get("/api/auth/config")
def auth_config(req: Request) -> dict:
    deps.limited(req, "auth")
    cfg = config.load()
    enabled = oidc_svc.is_enabled(cfg)
    return {
        "oidc": {
            "enabled": enabled,
            "provider_name": cfg.OIDC_PROVIDER_NAME or "SSO",
            "auto_redirect": bool(enabled and cfg.OIDC_AUTO_REDIRECT),
        },
        "password_login": not cfg.DISABLE_PASSWORD_LOGIN,
        "registration": "closed" if cfg.DISABLE_PASSWORD_LOGIN else cfg.REGISTRATION,
    }


@router.get("/api/oidc/login")
async def oidc_login(req: Request, join: str = "") -> RedirectResponse:
    cfg = config.load()
    try:
        deps.limited(req, "auth")
    except HTTPException as exc:
        if exc.status_code == 429 and oidc_svc.is_enabled(cfg):
            return RedirectResponse("/?oidc_error=rate_limited", status_code=302)
        raise
    if not oidc_svc.is_enabled(cfg):
        raise HTTPException(404, "OIDC not enabled")
    try:
        auth_url, state_cookie = await oidc_svc.start_login(req, cfg, join=join.strip()[:200])
    except oidc_svc.OidcError as exc:
        log.warning("oidc login start failed: %s", exc.message)
        return RedirectResponse(f"/?oidc_error={exc.code}", status_code=302)
    res = RedirectResponse(auth_url, status_code=302)
    res.set_cookie(
        oidc_svc.STATE_COOKIE,
        state_cookie,
        max_age=oidc_svc.STATE_TTL,
        path=oidc_svc.STATE_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(req),
    )
    return res


@router.get("/api/oidc/callback")
async def oidc_callback(req: Request) -> RedirectResponse:
    cfg = config.load()
    secure = _cookie_secure(req)
    try:
        deps.limited(req, "login")
    except HTTPException as exc:
        if exc.status_code == 429 and oidc_svc.is_enabled(cfg):
            res = RedirectResponse("/?oidc_error=rate_limited", status_code=302)
            res.delete_cookie(oidc_svc.STATE_COOKIE, path=oidc_svc.STATE_COOKIE_PATH, samesite="lax", secure=secure, httponly=True)
            return res
        raise
    if not oidc_svc.is_enabled(cfg):
        raise HTTPException(404, "OIDC not enabled")
    try:
        username, join_tok = await oidc_svc.complete_login(req, cfg)
    except oidc_svc.OidcError as exc:
        log.warning("oidc callback failed (%s): %s", exc.code, exc.message)
        res = RedirectResponse(f"/?oidc_error={exc.code}", status_code=302)
        res.delete_cookie(oidc_svc.STATE_COOKIE, path=oidc_svc.STATE_COOKIE_PATH, samesite="lax", secure=secure, httponly=True)
        return res
    old_tok = deps.session_token(req)
    if old_tok:
        sync.drop_sess_token(old_tok)
        await asyncio.to_thread(auth.delete_session, old_tok)
    token = await asyncio.to_thread(auth.mint, username)
    dest = f"/?join={quote(join_tok, safe='')}" if join_tok else "/"
    res = RedirectResponse(dest, status_code=302)
    set_cookie(res, req, token)
    res.delete_cookie(oidc_svc.STATE_COOKIE, path=oidc_svc.STATE_COOKIE_PATH, samesite="lax", secure=secure, httponly=True)
    return res
