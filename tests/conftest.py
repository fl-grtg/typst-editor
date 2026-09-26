"""Tmp SQLite + Files Isolation pro Test."""
import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend import db


@pytest.fixture()
def c(tmp_path, monkeypatch):
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
