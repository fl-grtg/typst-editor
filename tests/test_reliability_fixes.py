"""Round-3 reliability fixes: request size gates, proposal save split,
quota mutex, comment list caps and post-commit failure tolerance."""
import asyncio
import sqlite3
import threading
import time

import pytest
from conftest import make_doc, register_user
from fastapi import HTTPException

from backend import db, deps, sync
from backend import main as backend_main
from backend.routers import change_packages as proposal_routes
from backend.services import project_history, quota


def test_request_size_gate_rejects_oversized_content_length(c, monkeypatch):
    register_user(c, "alice")
    # Default ceiling (32 MB) lets normal bodies through.
    assert c.post("/api/docs/create", json={"title": "Ok", "content": "x"}).status_code == 200
    monkeypatch.setattr(backend_main, "MAX_REQUEST_BYTES", 8)
    response = c.post("/api/docs/create", json={"title": "Big", "content": "x"})
    assert response.status_code == 413, response.text
    assert response.json() == {"detail": "Request body too large"}


def test_read_capped_body_allows_up_to_cap():
    class FakeReq:
        def __init__(self, chunks):
            self._chunks = chunks

        def stream(self):
            async def gen():
                for part in self._chunks:
                    yield part

            return gen()

    assert asyncio.run(deps.read_capped_body(FakeReq([b"a" * 100, b"b" * 100]), 200)) == b"a" * 100 + b"b" * 100
    with pytest.raises(HTTPException) as error:
        asyncio.run(deps.read_capped_body(FakeReq([b"a" * 100, b"b" * 100]), 199))
    assert error.value.status_code == 413


def test_proposal_endpoints_reject_bodies_over_read_cap(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Caps", "old")
    project = c.get(f"/api/docs/{did}").json()["project_id"]
    monkeypatch.setattr(proposal_routes, "MAX_REQUEST_BYTES", 8)
    body = {"title": "Review me", "files": [
        {"kind": "document", "doc_id": did, "path": "main.typ", "action": "modify",
         "base": "old", "content": "new", "changes": [{"old_string": "old", "new_string": "new"}]}]}
    response = c.post(f"/api/projects/{project}/proposals", json=body)
    assert response.status_code == 413, response.text
    assert response.json() == {"detail": "Request body too large"}


def test_proposal_endpoint_keeps_400_for_malformed_body(c):
    register_user(c, "alice")
    did = make_doc(c, "Badjson", "old")
    project = c.get(f"/api/docs/{did}").json()["project_id"]
    response = c.post(f"/api/projects/{project}/proposals", content=b"not-json",
                      headers={"content-type": "application/json"})
    assert response.status_code == 400, response.text


def test_list_comments_caps_and_degrades_suggestion_fields(c):
    register_user(c, "alice")
    big = "x" * 5000
    did = make_doc(c, "Caps", big + "\nsmall anchor\n")
    c.post(f"/api/docs/{did}/suggestions", json={"old_string": big, "new_string": "y" * 5000})
    c.post(f"/api/docs/{did}/suggestions", json={"old_string": "small anchor", "new_string": "small replaced"})
    comments = c.get(f"/api/docs/{did}/comments").json()["comments"]
    oversized = next(m for m in comments if len(m["replacement"]) == 4000)
    small = next(m for m in comments if m["suggestion_old"] == "small anchor")
    # An oversized old degrades to "" instead of a truncated copy (uniqueness).
    assert oversized["suggestion_old"] == ""
    assert len(oversized["replacement"]) == 4000  # render-only cap
    # Under-cap values pass through unchanged.
    assert small["suggestion_old"] == "small anchor"
    assert small["replacement"] == "small replaced"


def test_accept_survives_broadcast_failure(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Bcast", "old")
    project = c.get(f"/api/docs/{did}").json()["project_id"]
    files = [{"kind": "document", "doc_id": did, "path": "main.typ", "action": "modify",
              "base": "old", "content": "new", "changes": [{"old_string": "old", "new_string": "new"}]}]
    created = c.post(f"/api/projects/{project}/proposals", json={"title": "Review me", "files": files}).json()

    async def boom(*args, **kwargs):
        raise RuntimeError("socket gone")

    monkeypatch.setattr(sync, "bcast", boom)
    accepted = c.post(f"/api/projects/{project}/proposals/{created['id']}/accept",
                      json={"revision": created["revision"]})
    assert accepted.status_code == 200, accepted.text
    assert c.get(f"/api/docs/{did}").json()["content"] == "new"


def test_save_survives_auto_document_failure(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "SnapFail", "old")

    def broken(doc_id):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(project_history, "auto_document", broken)
    response = c.post(f"/api/docs/{did}/save", json={"content": "new"})
    assert response.status_code == 200, response.text
    assert c.get(f"/api/docs/{did}").json()["content"] == "new"


def test_auto_document_lookup_swallows_db_errors(monkeypatch):
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "connect", broken)
    assert project_history.auto_document("d_missing") is None


def test_quota_guard_serializes_writers_of_one_owner(monkeypatch):
    calls = []
    a_inside = threading.Event()
    release = threading.Event()

    def fake_bytes(owner, con=None):
        calls.append("check")
        return 0

    monkeypatch.setattr(quota, "user_bytes", fake_bytes)
    monkeypatch.setattr(quota, "user_cap", lambda *a, **k: 10 ** 6)

    def writer_a():
        with quota.quota_guard("alice", 0):
            a_inside.set()
            release.wait(2.0)

    def writer_b():
        with quota.quota_guard("alice", 0):
            calls.append("body")

    a = threading.Thread(target=writer_a)
    a.start()
    assert a_inside.wait(2.0)
    b = threading.Thread(target=writer_b)
    b.start()
    time.sleep(0.1)  # B must be parked at the owner mutex, not run through
    assert "body" not in calls
    release.set()
    a.join(2.0)
    b.join(2.0)
    # A's post-check strictly precedes B's pre-check: serialized window.
    assert calls == ["check", "check", "check", "body", "check"]
