"""Account routes: login, registration, sessions, API keys, profile."""
from __future__ import annotations

import base64
import hmac
import logging
import re
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from backend import auth, config, db, deps, sync
from backend.constants import MAX_PW, MIN_PW, NAME_RE
from backend.schemas import AvatarSet, KeyCreate, Login, NameChange, PwChange, PwOnly, Register
from backend.services import quota as quota_svc
from backend.services.apikeys import _ROLE_RANK, KEY_ROLES, me_with_key, mint_api_key
from backend.services.locks import _drop_user_locks, _named_lock
from backend.services.proxy import _proxy_trusted
from backend.services.tutorial import TUTORIAL

log = logging.getLogger("typst.main")

router = APIRouter()


def _invite_ok(invite: str, token: str) -> bool:
    """Constant-time invite check; False for empty/non-ASCII (no 500)."""
    try:
        return bool(token) and bool(invite) and hmac.compare_digest(invite.encode(), token.encode())
    except Exception:
        return False


@router.post("/api/login")
def login(b: Login, res: Response, req: Request) -> dict:
    name = b.username.strip()
    deps.limited(req, "login", name.lower())
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
    if _proxy_trusted(req):
        proto = ((req.headers.get("x-forwarded-proto", "") or proto).split(",")[-1].strip().lower() or proto)
    return proto == "https"


def set_cookie(res: Response, req: Request, token: str) -> None:
    cfg = config.load()
    res.set_cookie(deps.COOKIE, token, max_age=min(max(cfg.SESSION_SECONDS, 3600), 90 * 86400),
                   path="/", httponly=True, samesite="lax", secure=_cookie_secure(req))


def clear_cookie(res: Response, req: Request) -> None:
    res.delete_cookie(deps.COOKIE, path="/", samesite="lax", secure=_cookie_secure(req), httponly=True)


@router.post("/api/register")
def register(b: Register, res: Response, req: Request) -> dict:
    name = b.username.strip()
    deps.limited(req, "register", name.lower())
    cfg = config.load()
    if cfg.REGISTRATION not in ("open", "invite-only", "closed"):
        log.warning("register blocked (bad mode)")
        raise HTTPException(403, "Registration disabled")
    if not re.fullmatch(NAME_RE, name):
        raise HTTPException(400, "Name: 2-20 chars, letters/numbers/_-")
    if not MIN_PW <= len(b.password) <= MAX_PW:
        raise HTTPException(400, "Password: 8-200 chars")
    with _named_lock("register"):
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
            raise deps.busy_503("register", e) from e
    token = auth.mint(name)
    set_cookie(res, req, token)
    return {"user": name}


@router.post("/api/logout")
async def logout(req: Request, res: Response) -> dict:
    deps.limited(req, "auth")
    tok = req.cookies.get(deps.COOKIE, "")
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


@router.get("/api/me")
def get_me(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "auth")  # own auth bucket: must not share files_list with preview polling
    con = db.connect()
    try:
        r = con.execute("SELECT avatar FROM users WHERE name=?", (user,)).fetchone()
        return {"user": user, "hasAvatar": bool(r and r["avatar"])}
    finally:
        con.close()


@router.post("/api/keys")
def create_key(b: KeyCreate, req: Request, authn: tuple[str, str] = Depends(me_with_key)) -> dict:
    user, cap = authn
    deps.limited(req, "keys", user)
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


@router.get("/api/keys")
def list_keys(req: Request, authn: tuple[str, str] = Depends(me_with_key)) -> dict:
    user, _cap = authn
    deps.limited(req, "keys", user)
    con = db.connect()
    try:
        rows = con.execute("SELECT id, name, prefix, role, expires_at, last_used, created_at FROM api_keys "
                           "WHERE username=? AND revoked=0 ORDER BY created_at", (user,)).fetchall()
        return {"keys": [dict(r) for r in rows]}
    finally:
        con.close()


@router.delete("/api/keys/{kid}")
def revoke_key(kid: str, req: Request, authn: tuple[str, str] = Depends(me_with_key)) -> dict:
    user, _cap = authn
    deps.limited(req, "keys", user)
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


@router.post("/api/me/password")
async def change_password(b: PwChange, req: Request, res: Response, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "pw")
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


@router.post("/api/me/name")
async def rename_me(b: NameChange, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "pw")
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


@router.post("/api/me/avatar")
def set_avatar(b: AvatarSet, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "avatar")
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
        raise deps.busy_503("set_avatar", e) from e
    return {"ok": True}


@router.delete("/api/me/avatar")
def del_avatar(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "avatar")
    con = db.connect()
    try:
        con.execute("UPDATE users SET avatar='' WHERE name=?", (user,))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@router.get("/api/avatar/{username}")
def get_avatar(username: str, req: Request, user: str = Depends(deps.me)) -> Response:
    deps.limited(req, "files_list")
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


@router.post("/api/me/delete")
async def delete_me(b: PwOnly, req: Request, res: Response, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "pw")
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
        src = deps.get_files_dir() / did
        if src.is_dir():
            dst = deps.get_files_dir() / f".trash-{did}"
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
        raise deps.busy_503("delete_me", e) from e
    for did in owned:
        await sync.drop(did)
    for _src, dst in trashed_dirs:
        try:
            shutil.rmtree(dst, ignore_errors=True)
        except OSError:
            log.warning("delete_me %s: rmtree failed", dst.name)
    await sync.kick_all(user)
    _drop_user_locks(user)
    if req.cookies.get(deps.COOKIE):
        auth.delete_session(req.cookies[deps.COOKIE])
    clear_cookie(res, req)
    return {"ok": True}
