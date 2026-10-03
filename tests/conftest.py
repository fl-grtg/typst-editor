"""Tmp SQLite + Files Isolation pro Test."""
import time

import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend import db, ratelimit, sync


@pytest.fixture(autouse=True)
def _clear_ratelimit():
    ratelimit.clear()
    yield
    ratelimit.clear()


@pytest.fixture(autouse=True)
def _clear_sync():
    sync.rooms.clear()
    sync._sess_cache.clear()
    main._SIDEBAR_Q.clear()
    with main._DOC_LOCKS_GUARD:
        main._DOC_LOCKS.clear()
        main._EXPORT_LOCKS.clear()
    yield
    sync.rooms.clear()
    sync._sess_cache.clear()
    main._SIDEBAR_Q.clear()
    with main._DOC_LOCKS_GUARD:
        main._DOC_LOCKS.clear()
        main._EXPORT_LOCKS.clear()


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("REGISTRATION", "open")  # Tests need open registration (Prod default is invite-only)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(main, "FILES_DIR", tmp_path / "files")
    db.init_db()
    with TestClient(main.app) as client:
        yield client


def register_user(c, name, pw="pass1234"):
    r = c.post("/api/register", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()


def login(c, name, pw="pass1234"):
    c.post("/api/logout")
    r = c.post("/api/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()


def make_doc(c, title="Doc", content="hi"):
    r = c.post("/api/docs/create", json={"title": title, "content": content})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def wait_for(pred, timeout=5.0, msg="condition not met"):
    deadline = time.monotonic() + timeout
    while True:
        try:
            if pred():
                return
        except Exception:
            pass  # transient error (e.g. httpx): retry until deadline
        if time.monotonic() >= deadline:
            raise AssertionError(msg)
        time.sleep(0.05)
