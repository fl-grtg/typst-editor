"""Wave 1C proofs: write-behind, session revoke, compile 503, rehash.

Backend tests patch deps.* (never main.*) via the `c` fixture.
"""
import hashlib

import pytest
from conftest import login, make_doc, register_user
from pycrdt import Doc, Text
from ws_helpers import _parse, _step1, _update_msg

from backend import auth, db, deps, sync
from backend import mcp_tools as t


def _db_content(doc_id):
    con = db.connect()
    try:
        row = con.execute("SELECT content FROM docs WHERE id=?", (doc_id,)).fetchone()
        return row["content"] if row else None
    finally:
        con.close()


def test_write_behind_flush_marks_dirty_then_persists(c):
    """WS update marks dirty without immediate DB write; flush persists."""
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "WB", content="base")
    assert _db_content(did) == "base"
    with c.websocket_connect(f"/ws/{did}") as wa:
        wa.receive_bytes()  # step1
        with c.websocket_connect(f"/ws/{did}") as wb:
            wb.receive_bytes()
            adoc = Doc()
            wa.send_bytes(_step1())
            _, _, diff = _parse(wa.receive_bytes())
            adoc.apply_update(diff)
            with adoc.transaction():
                adoc.get("typst", type=Text).__iadd__("-edit")
            wa.send_bytes(_update_msg(adoc))
            # B receives the broadcast: server processed the update.
            t2, st2, _ = _parse(wb.receive_bytes())
            assert (t2, st2) == (sync.MSG_SYNC, sync.UPDATE)
            # Live room shows the edit immediately...
            assert "-edit" in (sync.room_text(did) or "")
            # ...but the room is dirty (write-behind, window = 2s).
            r = sync.rooms.get(did)
            assert r is not None and r.get("dirty") is True
            # DB still holds the old content before the flush.
            assert _db_content(did) == "base"
            # Explicit flush persists (flusher does this every 2s + on disconnect).
            sync.flush_all()
            assert "-edit" in (_db_content(did) or "")
            assert sync.rooms.get(did, {}).get("dirty") in (False, None)


def test_write_behind_disconnect_flushes(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "WB2", content="start")
    with c.websocket_connect(f"/ws/{did}") as ws:
        ws.receive_bytes()
        doc = Doc()
        ws.send_bytes(_step1())
        _, _, diff = _parse(ws.receive_bytes())
        doc.apply_update(diff)
        with doc.transaction():
            doc.get("typst", type=Text).__iadd__("-v2")
        ws.send_bytes(_update_msg(doc))
        # Wait for the server to apply the update before disconnecting
        # (else close races the in-flight UPDATE and the room never dirties).
        import time as _t
        _dead = _t.monotonic() + 5.0
        while _t.monotonic() < _dead:
            if "-v2" in (sync.room_text(did) or ""):
                break
            _t.sleep(0.05)
        assert "-v2" in (sync.room_text(did) or "")
    # Disconnect flushes (last-disconnect rule): DB catches up without flush_all.
    import time as _time
    deadline = _time.monotonic() + 5.0
    while _time.monotonic() < deadline:
        if "-v2" in (_db_content(did) or ""):
            break
        _time.sleep(0.05)
    assert "-v2" in (_db_content(did) or "")


def test_session_list_and_single_revoke(c):
    register_user(c, "alice")
    tok_a = c.cookies.get(auth.COOKIE)
    assert tok_a
    # Second session WITHOUT logging out the first (login() helper logs out).
    r_login = c.post("/api/login", json={"username": "alice", "password": "pass1234"})
    assert r_login.status_code == 200, r_login.text
    tok_b = c.cookies.get(auth.COOKIE)
    assert tok_b and tok_b != tok_a
    r = c.get("/api/sessions")
    assert r.status_code == 200, r.text
    sess = r.json()["sessions"]
    assert len(sess) == 2
    ids = {s["id"] for s in sess}
    assert auth.sha(tok_a) in ids and auth.sha(tok_b) in ids
    cur = [s for s in sess if s["current"]]
    assert len(cur) == 1 and cur[0]["id"] == auth.sha(tok_b)
    # Revoke the first session; second stays valid.
    rr = c.delete(f"/api/sessions/{auth.sha(tok_a)}")
    assert rr.status_code == 200, rr.text
    r2 = c.get("/api/sessions")
    assert len(r2.json()["sessions"]) == 1
    c.cookies.set(auth.COOKIE, tok_a)
    assert c.get("/api/me").status_code == 401
    c.cookies.set(auth.COOKIE, tok_b)
    assert c.get("/api/me").status_code == 200
    # Bad id -> 404, no leak.
    assert c.delete("/api/sessions/nothex").status_code == 404
    assert c.delete("/api/sessions/" + "0" * 64).status_code == 404


def test_session_revoke_current_clears_cookie(c):
    register_user(c, "alice")
    tok = c.cookies.get(auth.COOKIE)
    r = c.delete(f"/api/sessions/{auth.sha(tok)}")
    assert r.status_code == 200, r.text
    assert c.get("/api/me").status_code == 401


def test_compile_503_under_contention(c, monkeypatch):
    """Holds all compile slots + fills queue -> 503 with Retry-After."""
    monkeypatch.setattr(t, "COMPILE_QUEUE_MAX", 0)
    held = []
    for _ in range(t.COMPILE_MAX_CONCURRENT):
        assert t._COMPILE_SLOTS.acquire(blocking=False)
        held.append(True)
    try:
        with pytest.raises(Exception) as e:
            t._typst_compile(["compile", "--help"], "/tmp")
        assert getattr(e.value, "status_code", 0) == 503
        assert e.value.headers.get("Retry-After") == str(t.COMPILE_RETRY_AFTER_S)
        with pytest.raises(Exception) as e2:
            t._compile_pngs("= Hi", [], "1")
        assert getattr(e2.value, "status_code", 0) == 503
    finally:
        for _ in held:
            t._COMPILE_SLOTS.release()
    # Slots free again: missing typst -> 500 (not 503).
    monkeypatch.setattr(t.shutil, "which", lambda *a, **k: None)
    with pytest.raises(Exception) as e3:
        t._typst_compile(["compile", "--help"], "/tmp")
    assert getattr(e3.value, "status_code", 0) == 500


def test_compile_env_whitelist_no_invite_leak(c, monkeypatch):
    monkeypatch.setenv("REGISTRATION_INVITE_TOKEN", "super-secret-invite")
    monkeypatch.setenv("SECRET_X", "shhh")
    env = t._typst_env(deps.get_files_dir())
    flat = " ".join(f"{k}={v}" for k, v in env.items())
    assert "super-secret-invite" not in flat
    assert "shhh" not in flat
    assert "REGISTRATION_INVITE_TOKEN" not in env
    assert env.get("TYPST_PACKAGE_CACHE_PATH")
    assert env.get("XDG_CACHE_HOME")


def test_rehash_on_login_upgrades_old_hash(c):
    register_user(c, "alice")
    # Simulate a pre-1C account with 300k rounds.
    import secrets as _sec
    salt = _sec.token_bytes(16)
    old_digest = hashlib.pbkdf2_hmac("sha256", b"pass1234", salt, 300_000)
    old_hash = f"pbkdf2$300000${salt.hex()}${old_digest.hex()}"
    assert auth.needs_rehash(old_hash) is True
    con = db.connect()
    try:
        con.execute("UPDATE users SET hash=? WHERE name=?", (old_hash, "alice"))
        con.commit()
    finally:
        con.close()
    c.post("/api/logout")
    r = c.post("/api/login", json={"username": "alice", "password": "pass1234"})
    assert r.status_code == 200, r.text
    con = db.connect()
    try:
        row = con.execute("SELECT hash FROM users WHERE name=?", ("alice",)).fetchone()
        new_hash = row["hash"]
    finally:
        con.close()
    assert auth.needs_rehash(new_hash) is False
    assert new_hash.split("$", 3)[1] == str(auth.CURRENT_ROUNDS)
    assert int(new_hash.split("$", 3)[1]) >= 600_000


def test_avatar_set_delete_invalidate_quota_cache(c, monkeypatch):
    """Avatar set/delete drop the WS quota verdict (R1 blocker 2 contract).

    Prime the short-lived quota cache, verify the cached verdict is served
    without a recheck, then prove avatar set AND delete each force a recheck
    (cache-miss counter on services.quota.is_over_quota).
    """
    import asyncio as _asyncio
    import base64 as _b64

    from backend.services import quota as _quota_svc

    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Q", content="x")
    calls = {"n": 0}

    def _counting(user):
        calls["n"] += 1
        return False

    monkeypatch.setattr(_quota_svc, "is_over_quota", _counting)
    assert _asyncio.run(sync._quota_ok_cached_async(did)) is True
    assert calls["n"] == 1
    # Fresh cache entry: served without a recheck.
    assert _asyncio.run(sync._quota_ok_cached_async(did)) is True
    assert calls["n"] == 1
    # Avatar set invalidates -> next flush path rechecks.
    img = "data:image/png;base64," + _b64.b64encode(b"fakepngdata").decode()
    r = c.post("/api/me/avatar", json={"img": img})
    assert r.status_code == 200, r.text
    assert "alice" not in sync._quota_cache
    assert _asyncio.run(sync._quota_ok_cached_async(did)) is True
    assert calls["n"] == 2
    # Avatar delete invalidates too.
    r = c.delete("/api/me/avatar")
    assert r.status_code == 200, r.text
    assert "alice" not in sync._quota_cache
    assert _asyncio.run(sync._quota_ok_cached_async(did)) is True
    assert calls["n"] == 3


def test_new_hash_uses_600k_rounds():
    h = auth.hash_password("pass1234")
    assert h.split("$", 3)[1] == str(auth.CURRENT_ROUNDS)
    assert int(h.split("$", 3)[1]) >= 600_000
    assert auth.check_password("pass1234", h) is True
    assert auth.check_password("wrongpass1", h) is False


def test_b1_room_race_single_doc(c):
    """B1: 20 parallele Erst-Connects -> genau 1 Doc-Objekt, kein Dirt-Verlust."""
    import concurrent.futures as _fut
    import threading as _th

    from pycrdt import Text as _Text

    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "B1Race", content="base")
    sync.rooms.pop(did, None)
    n = 20
    barrier = _th.Barrier(n)
    out: list = [None] * n

    def _worker(i: int) -> None:
        barrier.wait(timeout=5.0)
        out[i] = sync.room(did)

    with _fut.ThreadPoolExecutor(max_workers=n) as ex:
        list(ex.map(_worker, range(n)))
    first = out[0]
    assert first is not None
    for r in out[1:]:
        assert r is first
    assert sync.rooms.get(did) is first
    # Kein Dirt-Verlust: Edit über eine Referenz ist über alle sichtbar.
    with sync._doc_lock(first):
        with first["doc"].transaction():
            first["doc"].get("typst", type=_Text).__iadd__("-b1")
    first["dirty"] = True
    for r in out:
        assert r.get("dirty") is True
    assert "-b1" in (sync.room_text(did) or "")


def test_b2_writer_flusher_consistent(c):
    """B2: parallele Writer+Flusher -> Inhalt konsistent (kein Datenrennen)."""
    import concurrent.futures as _fut

    from pycrdt import Text as _Text

    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "B2Race", content="base")
    r = sync.room(did)
    NW, NOPS, NF = 8, 20, 4

    def _writer(i: int) -> None:
        for j in range(NOPS):
            with sync._doc_lock(r):
                with r["doc"].transaction():
                    r["doc"].get("typst", type=_Text).__iadd__(f"-w{i}-{j}")
            r["dirty"] = True

    def _flusher() -> None:
        for _ in range(NOPS):
            try:
                sync.persist(did)
            except Exception:
                pass
            try:
                sync.flush_all()
            except Exception:
                pass

    with _fut.ThreadPoolExecutor(max_workers=NW + NF) as ex:
        futs = [ex.submit(_writer, i) for i in range(NW)]
        futs += [ex.submit(_flusher) for _ in range(NF)]
        for f in _fut.as_completed(futs, timeout=30):
            f.result()
    sync._quota_cache.clear()
    sync.flush_all()
    live = sync.room_text(did) or ""
    for i in range(NW):
        for j in range(NOPS):
            assert f"-w{i}-{j}" in live
    con = db.connect()
    try:
        row = con.execute("SELECT content FROM docs WHERE id=?", (did,)).fetchone()
        db_text = row["content"] if row else ""
    finally:
        con.close()
    assert db_text == live
    assert sync.save_status(did) is not None
    assert sync.save_status(did)["quota_blocked"] is False


def test_b5_foreign_revoke_kicks_idle_ws(c):
    """B5: Single-Revoke schließt fremde idle WS-Conns aktiv (Kick)."""
    import pytest as _pt
    from fastapi.websockets import WebSocketDisconnect as _WD

    register_user(c, "alice")
    tok_a = c.cookies.get(auth.COOKIE)
    assert tok_a
    r_login = c.post("/api/login", json={"username": "alice", "password": "pass1234"})
    assert r_login.status_code == 200, r_login.text
    tok_b = c.cookies.get(auth.COOKIE)
    assert tok_b and tok_b != tok_a
    did = make_doc(c, "B5Kick", content="hi")
    # Fremde Session (wird revoked) + eigene Survivor-Session.
    c.cookies.set(auth.COOKIE, tok_a)
    with c.websocket_connect(f"/ws/{did}") as wa:
        wa.receive_bytes()
        c.cookies.set(auth.COOKIE, tok_b)
        with c.websocket_connect(f"/ws/{did}") as wb:
            wb.receive_bytes()
            # Revoke der fremden Session als Survivor.
            rr = c.delete(f"/api/sessions/{auth.sha(tok_a)}")
            assert rr.status_code == 200, rr.text
            # Idle Fremd-Client wird getrennt (Close 4403), kein Broadcast mehr.
            with _pt.raises(_WD) as ei:
                wa.receive_bytes()
            assert ei.value.code == 4403
            # Survivor lebt: STEP1 -> STEP2 antwortet noch.
            wb.send_bytes(_step1())
            _t, _s, _d = _parse(wb.receive_bytes())
            assert (_t, _s) == (sync.MSG_SYNC, sync.STEP2)


def test_b6_session_async_fail_closed(c, monkeypatch):
    """B6: _session_async fail-closed bei DB-Exception (wie session_ok)."""
    import asyncio as _aio
    import time as _tm

    from backend.constants import SESSION_RECHECK_TTL as _TTL

    register_user(c, "alice")
    tok = c.cookies.get(auth.COOKIE)
    assert tok
    sync._sess_cache.clear()

    def _boom(_t: str):
        raise RuntimeError("db down")

    monkeypatch.setattr(auth, "verify_session", _boom)
    # Cache-miss + DB-Fehler -> None (kein Zutritt).
    assert _aio.run(sync._session_async(tok)) is None
    # Stale Hit + DB-Fehler -> ebenfalls None (kein fail-open).
    sync._sess_cache[tok] = ("alice", _tm.monotonic() - _TTL - 1.0)
    assert _aio.run(sync._session_async(tok)) is None


def test_b7_typst_tag_sandbox(c, monkeypatch):
    """B7: _typst_tag läuft in der Sandbox (Slot + env-Whitelist + preexec)."""
    import sys as _sys

    monkeypatch.setenv("REGISTRATION_INVITE_TOKEN", "tag-secret-invite")
    monkeypatch.setenv("SECRET_X_TAG", "tag-shhh")
    seen: dict = {}

    class _FakeProc:
        stdout = b"typst 0.12.0 (test)"
        returncode = 0

    def _fake_run(cmd, **kw):
        seen.update(kw)
        seen["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(t.shutil, "which", lambda *a, **k: "/usr/bin/typst")
    monkeypatch.setattr(t.subprocess, "run", _fake_run)
    t._TYPST_TAG = None
    try:
        tag = t._typst_tag()
    finally:
        t._TYPST_TAG = None
    assert tag.startswith("typst 0.12.0")
    env = seen.get("env") or {}
    flat = " ".join(f"{k}={v}" for k, v in env.items())
    assert "tag-secret-invite" not in flat
    assert "tag-shhh" not in flat
    assert "REGISTRATION_INVITE_TOKEN" not in env
    assert env.get("TYPST_PACKAGE_CACHE_PATH")
    if _sys.platform != "win32":
        assert seen.get("preexec_fn") is not None
    # Volle Slots -> 503-Fallback "unknown", kein subprocess-Aufruf.
    monkeypatch.setattr(t, "COMPILE_QUEUE_MAX", 0)
    held = []
    for _ in range(t.COMPILE_MAX_CONCURRENT):
        assert t._COMPILE_SLOTS.acquire(blocking=False)
        held.append(True)
    called = {"n": 0}

    def _must_not_run(*a, **k):
        called["n"] += 1
        raise AssertionError("must not run when slots are full")

    monkeypatch.setattr(t.subprocess, "run", _must_not_run)
    t._TYPST_TAG = None
    try:
        assert t._typst_tag() == "unknown"
    finally:
        t._TYPST_TAG = None
        for _ in held:
            t._COMPILE_SLOTS.release()
    assert called["n"] == 0


def test_b4_quota_persist_under_over(c, monkeypatch):
    """B4/G4-4: persist/flush_all enforcen Quota ohne stillen Datenverlust."""
    from backend.services import quota as _qs

    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "B4Q", content="base")
    r = sync.room(did)

    def _dirty(text: str) -> None:
        from pycrdt import Text as _Text

        with sync._doc_lock(r):
            with r["doc"].transaction():
                cur = r["doc"].get("typst", type=_Text)
                cur.clear()
                cur += text
        r["dirty"] = True
        r["text_len"] = len(text)

    # Under-quota persistiert (beide Pfade: persist + flush_all).
    sync._quota_cache.clear()
    monkeypatch.setattr(_qs, "is_over_quota", lambda _u: False)
    _dirty("under-ok")
    assert sync.persist(did) is True
    assert _db_content(did) == "under-ok"
    assert sync.rooms[did].get("dirty") in (False, None)
    assert sync.save_status(did)["quota_blocked"] is False
    _dirty("under-ok2")
    sync.flush_all()
    assert _db_content(did) == "under-ok2"
    assert sync.save_status(did)["quota_blocked"] is False
    # Over-quota: weder persistiert noch gedroppt (dirty + sichtbarer Status).
    sync._quota_cache.clear()
    monkeypatch.setattr(_qs, "is_over_quota", lambda _u: True)
    _dirty("over-blocked-content")
    assert sync.persist(did) is False
    assert _db_content(did) == "under-ok2"
    assert sync.rooms[did].get("dirty") is True
    st = sync.save_status(did)
    assert st is not None and st["dirty"] is True and st["quota_blocked"] is True
    sync.flush_all()
    assert _db_content(did) == "under-ok2"
    assert sync.rooms[did].get("dirty") is True
    assert sync.save_status(did)["quota_blocked"] is True
    # Disconnect-Pfad (persist) behält Dirt ebenfalls; nächster Connect meldet.
    assert sync.persist(did) is False
    assert sync.save_status(did)["quota_blocked"] is True
    assert "over-blocked-content" in (sync.room_text(did) or "")
