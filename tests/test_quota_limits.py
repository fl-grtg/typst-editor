"""Quota/limits: exact boundary ok, over -> 400/413."""
from types import SimpleNamespace

import pytest
from conftest import make_doc, register_user
from fastapi import HTTPException

from backend import config as backend_config
from backend import main as backend_main


def _patch(monkeypatch, **kw):
    real = backend_config.load()
    monkeypatch.setattr(backend_config, "load", lambda: SimpleNamespace(**{**vars(real), **kw}))


def test_limit_defaults():
    cfg = backend_config.load()
    assert cfg.MAX_DOCS_PER_USER == 100
    assert cfg.MAX_FILES_PER_DOC == 200
    assert cfg.MAX_BYTES_PER_USER == 500 * 1024 * 1024
    assert backend_main.EXPORT_MAX == 100 * 1024 * 1024


def test_check_quota_exact_ok_over_413(c, monkeypatch):
    register_user(c, "alice")
    used = backend_main.user_bytes("alice")
    _patch(monkeypatch, MAX_BYTES_PER_USER=used + 10)
    backend_main.check_quota("alice", 10)  # exactly at limit ok
    with pytest.raises(HTTPException) as e:
        backend_main.check_quota("alice", 11)
    assert e.value.status_code == 413


def test_quota_create_boundary(c, monkeypatch):
    register_user(c, "alice")
    used = backend_main.user_bytes("alice")
    _patch(monkeypatch, MAX_BYTES_PER_USER=used + 5)
    assert c.post("/api/docs/create", json={"title": "Passt", "content": "x" * 5}).status_code == 200
    assert c.post("/api/docs/create", json={"title": "Drueber", "content": "y"}).status_code == 413


def test_max_docs_boundary(c, monkeypatch):
    _patch(monkeypatch, MAX_DOCS_PER_USER=2)
    register_user(c, "alice")  # tutorial = doc 1
    assert c.post("/api/docs/create", json={"title": "Zweites"}).status_code == 200  # at limit ok
    assert c.post("/api/docs/create", json={"title": "Drittes"}).status_code == 400  # over -> 400


def test_max_files_boundary(c, monkeypatch):
    _patch(monkeypatch, MAX_FILES_PER_DOC=2)
    register_user(c, "alice")
    did = make_doc(c, "Dateien")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("a.png", b"1")}).status_code == 200
    assert c.post(f"/api/docs/{did}/files", files={"f": ("b.png", b"2")}).status_code == 200
    assert c.post(f"/api/docs/{did}/files", files={"f": ("c.png", b"3")}).status_code == 400
