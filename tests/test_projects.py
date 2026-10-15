"""Project inheritance, isolated libraries and explicit resource copying."""
from conftest import login, register_user

from backend import db


def setup_project(c):
    register_user(c, "alice")
    c.post("/api/templates", json={"name": "layout.typ", "content": "Owner layout"})
    c.post("/api/templates", json={"name": "private.typ", "content": "SECRET"})
    r = c.post("/api/docs/create", json={"title": "Team", "content": '#include "layout.typ"'})
    assert r.status_code == 200, r.text
    did = r.json()["id"]
    pid = c.get(f"/api/docs/{did}").json()["project_id"]
    assert c.get(f"/api/projects/{pid}/resources").json()["resources"][0]["name"] == "layout.typ"
    return pid, did


def test_project_inherits_new_documents_and_revokes(c):
    pid, did = setup_project(c)
    register_user(c, "bob")
    login(c, "alice")
    assert c.post(f"/api/projects/{pid}/members", json={"username": "bob", "role": "editor"}).status_code == 200
    login(c, "bob")
    assert db.doc_role("bob", did) == "editor"
    assert "bob" in c.get(f"/api/docs/{did}/members").json()["members"]
    assert did in [d["id"] for d in c.get("/api/docs").json()["shared"]]
    new = c.post(f"/api/projects/{pid}/docs", json={"title": "New", "folder": "chapters/sub"})
    assert new.status_code == 200, new.text
    nid = new.json()["id"]
    assert db.doc_role("bob", nid) == "editor"
    assert c.post(f"/api/projects/{pid}/resources", json={"name": "nested/new.typ", "content": "Shared"}).status_code == 200
    login(c, "alice")
    assert c.post(f"/api/projects/{pid}/members", json={"username": "bob", "role": "reviewer"}).status_code == 200
    login(c, "bob")
    assert c.post(f"/api/projects/{pid}/docs", json={"title": "Forbidden"}).status_code == 403
    assert c.post(f"/api/projects/{pid}/resources", json={"name": "bad.typ", "content": "No"}).status_code == 403
    login(c, "alice")
    assert c.delete(f"/api/projects/{pid}/members/bob").status_code == 200
    login(c, "bob")
    assert c.get(f"/api/docs/{did}").status_code == 404
    assert c.get(f"/api/projects/{pid}/resources").status_code == 404


def test_project_library_is_independent_and_local_wins(c):
    pid, did = setup_project(c)
    c.post("/api/templates", json={"name": "layout.typ", "content": "Changed private"})
    out = c.get(f"/api/docs/{did}/resources").json()
    assert out["project_id"] == pid
    assert out["resources"] == {"layout.typ": "Owner layout"}
    c.post(f"/api/docs/{did}/files/layout.typ/text", json={"content": "Local"})
    assert "layout.typ" not in c.get(f"/api/docs/{did}/resources").json()["resources"]
    assert c.get("/api/templates/private.typ").status_code == 200


def test_project_editor_document_creation_invalidates_owner_quota(c):
    from backend import sync

    pid, _ = setup_project(c)
    register_user(c, "bob")
    login(c, "alice")
    assert c.post(f"/api/projects/{pid}/members", json={"username": "bob", "role": "editor"}).status_code == 200
    login(c, "bob")
    sync._quota_cache["alice"] = (False, 0)
    sync._quota_cache["bob"] = (False, 0)
    try:
        response = c.post(f"/api/projects/{pid}/docs", json={"title": "Editor created", "content": "New bytes"})
        assert response.status_code == 200, response.text
        assert "alice" not in sync._quota_cache
        assert "bob" in sync._quota_cache
    finally:
        sync._quota_cache.clear()


def test_automatic_project_creation_keeps_individual_shares_limited(c):
    register_user(c, "alice")
    did = c.post("/api/docs/create", json={"title": "Doc"}).json()["id"]
    pid = c.get(f"/api/docs/{did}").json()["project_id"]
    other = c.post(f"/api/projects/{pid}/docs", json={"title": "Other"}).json()["id"]
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"})
    login(c, "bob")
    assert c.get(f"/api/docs/{did}").status_code == 200
    assert c.get(f"/api/docs/{other}").status_code == 404
    project = c.get(f"/api/projects/{pid}").json()
    assert project["role"] == "guest"
    assert [d["id"] for d in project["documents"]] == [did]


def test_copy_preserves_original_checks_conflicts_and_stale_source(c):
    pid, did = setup_project(c)
    c.post(f"/api/docs/{did}/files/sub/piece.typ/text", json={"content": '#include "leaf.typ"'})
    body = {"source": "sub/piece.typ", "scope": "project", "project_id": pid, "name": "sub/piece.typ"}
    p = c.post(f"/api/docs/{did}/library-copy-preview", json=body)
    assert p.status_code == 200, p.text
    assert p.json()["dependencies"] == ["leaf.typ"]
    r = c.post(f"/api/docs/{did}/library-copy", json={**body, "preview": p.json()["preview"]})
    assert r.status_code == 200, r.text
    assert c.get(f"/api/docs/{did}/files/sub/piece.typ/text").status_code == 200
    assert c.post(f"/api/docs/{did}/library-copy", json={**body, "preview": p.json()["preview"]}).status_code == 409
    for name in ("sources.bib", "table.csv"):
        c.post(f"/api/docs/{did}/files/{name}/text", json={"content": "original"})
        b = {"source": name, "scope": "personal", "name": name, "folder": "Copied"}
        pv = c.post(f"/api/docs/{did}/library-copy-preview", json=b).json()
        assert c.post(f"/api/docs/{did}/library-copy", json={**b, "preview": pv["preview"]}).status_code == 200
        assert c.get(f"/api/templates/{name}").json()["content"] == "original"


def test_project_paths_resolve_relative_dependencies(c):
    from backend.services.resources import doc_effective

    pid, did = setup_project(c)
    for name, content in [("sub/a.typ", '#include "leaf.typ"'), ("sub/leaf.typ", "Nested")]:
        assert c.post(f"/api/projects/{pid}/resources", json={"name": name, "content": content}).status_code == 200
    out = doc_effective("alice", '#include "sub/a.typ"', {}, did)
    assert out["resources"] == {"sub/a.typ": '#include "leaf.typ"', "sub/leaf.typ": "Nested"}


def test_project_export_and_duplicate_use_shared_library(c):
    from backend.mcp_tools import _collect_export_source

    pid, did = setup_project(c)
    c.post("/api/templates", json={"name": "layout.typ", "content": "Private changed"})
    _, files, _ = _collect_export_source(did)
    assert dict(files)["layout.typ"] == b"Owner layout"
    duplicate = c.post(f"/api/docs/{did}/duplicate")
    assert duplicate.status_code == 200, duplicate.text
    new = duplicate.json()["id"]
    assert c.get(f"/api/docs/{new}").json()["project_id"] == pid
    assert c.get(f"/api/docs/{new}/resources").json()["resources"]["layout.typ"] == "Owner layout"


def test_project_duplicate_uses_owner_document_limit(c, monkeypatch):
    from dataclasses import replace

    from backend import config

    settings = replace(config.load(), MAX_DOCS_PER_USER=3)
    monkeypatch.setattr(config, "load", lambda: settings)
    pid, did = setup_project(c)
    register_user(c, "bob")
    for title in ("Personal one", "Personal two"):
        response = c.post("/api/docs/create", json={"title": title})
        assert response.status_code == 200, response.text
    personal_id = response.json()["id"]
    assert c.post(f"/api/docs/{personal_id}/duplicate").status_code == 400
    login(c, "alice")
    assert c.post(f"/api/projects/{pid}/members", json={"username": "bob", "role": "editor"}).status_code == 200
    login(c, "bob")
    duplicate = c.post(f"/api/docs/{did}/duplicate")
    assert duplicate.status_code == 200, duplicate.text
    with db.tx() as con:
        copied = con.execute("SELECT owner, project_id FROM docs WHERE id=?", (duplicate.json()["id"],)).fetchone()
    assert (copied["owner"], copied["project_id"]) == ("alice", pid)
    blocked = c.post(f"/api/docs/{did}/duplicate")
    assert blocked.status_code == 400, blocked.text
    assert blocked.json()["detail"] == "Too many docs"


def test_project_trash_restore_and_final_delete(c):
    pid, did = setup_project(c)
    assert c.delete(f"/api/projects/{pid}").status_code == 200
    assert pid not in [p["id"] for p in c.get("/api/projects").json()["projects"]]
    assert c.get(f"/api/docs/{did}").status_code == 410
    assert c.post(f"/api/docs/{did}/restore").status_code == 200
    assert c.get("/api/projects").json()["projects"][0]["id"] == pid
    assert c.get(f"/api/docs/{did}/resources").json()["resources"]["layout.typ"] == "Owner layout"
    c.delete(f"/api/projects/{pid}")
    assert c.delete(f"/api/docs/{did}").status_code == 200
    assert c.get(f"/api/projects/{pid}").status_code == 404


def test_project_quota_failure_is_atomic(c, monkeypatch):
    from backend.services import quota

    pid, did = setup_project(c)
    before = quota.user_bytes("alice")
    monkeypatch.setattr(quota, "quota_cap", lambda: before)
    assert c.post(f"/api/projects/{pid}/resources", json={"name": "over.typ", "content": "x"}).status_code == 413
    assert "over.typ" not in [r["name"] for r in c.get(f"/api/projects/{pid}/resources").json()["resources"]]
    assert c.get(f"/api/docs/{did}/resources").json()["resources"]["layout.typ"] == "Owner layout"


def test_project_resource_delete_guards_version(c):
    pid, _ = setup_project(c)
    row = c.get(f"/api/projects/{pid}/resources").json()["resources"][0]
    url = f"/api/projects/{pid}/resources/layout.typ"
    assert c.delete(url, params={"version": "stale"}).status_code == 409
    assert c.delete(url, params={"version": row["updated_at"]}).status_code == 200
    assert c.get(f"/api/projects/{pid}/resources").json()["resources"] == []


def test_project_members_read_whole_library_but_document_guests_only_reachable(c):
    pid, did = setup_project(c)
    c.post(f"/api/projects/{pid}/resources", json={"name": "unused.typ", "content": "Project-only"})
    register_user(c, "member")
    register_user(c, "guest")
    login(c, "alice")
    c.post(f"/api/projects/{pid}/members", json={"username": "member", "role": "reviewer"})
    c.post(f"/api/docs/{did}/share", json={"username": "guest", "role": "reviewer"})
    login(c, "member")
    assert "unused.typ" in c.get(f"/api/docs/{did}/resources").json()["resources"]
    login(c, "guest")
    assert c.get(f"/api/docs/{did}/resources").json()["resources"] == {"layout.typ": "Owner layout"}


def test_quota_check_observes_uncommitted_project_bytes(c, monkeypatch):
    import pytest
    from fastapi import HTTPException

    from backend.services import quota

    pid, _ = setup_project(c)
    before = quota.user_bytes("alice")
    monkeypatch.setattr(quota, "quota_cap", lambda: before)
    with db.tx() as con:
        con.execute("INSERT INTO project_resources VALUES (?,?,?,?)", (pid, "pending.typ", "one", db.now_iso()))
        with pytest.raises(HTTPException) as e:
            quota.check_quota("alice", 0, con)
        assert e.value.status_code == 413
