import base64
import sqlite3

import pytest
from conftest import login, make_doc, register_user
from fastapi import HTTPException
from pycrdt import Text

from backend import sync
from backend.services import quota


def setup(c, content="first old\nlast old\n"):
    register_user(c, "alice")
    document = make_doc(c, "Packages", content)
    project = c.get(f"/api/docs/{document}").json()["project_id"]
    return project, document


def document_change(document, base, changes):
    content = base
    for old, new in changes:
        content = content.replace(old, new)
    return {"kind": "document", "doc_id": document, "path": "main.typ", "action": "modify", "base": base,
            "content": content, "changes": [{"old_string": old, "new_string": new} for old, new in changes]}


def submit(c, project, files):
    response = c.post(f"/api/projects/{project}/proposals", json={"title": "Review me", "files": files})
    assert response.status_code == 200, response.text
    return response.json()


def accept(c, project, package, **selection):
    return c.post(f"/api/projects/{project}/proposals/{package['id']}/accept", json={"revision": package["revision"], **selection})


def test_submission_preserves_independent_source_edits(c):
    project, document = setup(c, "alpha beta gamma\n")
    draft = document_change(document, "alpha beta gamma\n", [("beta", "BETA")])
    current = "new introduction\nalpha beta gamma\n"
    assert c.post(f"/api/docs/{document}/save", json={"content": current, "force": True}).status_code == 200
    package = submit(c, project, [draft])
    assert package["files"][0]["base"] == current
    assert package["files"][0]["content"] == current.replace("beta", "BETA")
    assert c.get(f"/api/docs/{document}").json()["content"] == current
    assert accept(c, project, package).status_code == 200
    assert c.get(f"/api/docs/{document}").json()["content"] == current.replace("beta", "BETA")


def test_submission_conflict_keeps_current_source_untouched(c):
    project, document = setup(c, "alpha beta gamma\n")
    draft = document_change(document, "alpha beta gamma\n", [("beta", "BETA")])
    current = "alpha replaced gamma\n"
    assert c.post(f"/api/docs/{document}/save", json={"content": current, "force": True}).status_code == 200
    response = c.post(f"/api/projects/{project}/proposals", json={"title": "Conflict", "files": [draft]})
    assert response.status_code == 409
    assert c.get(f"/api/docs/{document}").json()["content"] == current
    assert c.get(f"/api/projects/{project}/proposals").json()["packages"] == []


@pytest.mark.parametrize("base,changes,current", [
    ("beta", [("beta", "beta version")], "beta version"),
    ("ab something bc", [("ab", "AB"), ("bc", "BC")], "abc"),
])
def test_submission_rebase_rejects_applied_insertions_and_new_overlaps(c, base, changes, current):
    project, document = setup(c, base)
    draft = document_change(document, base, changes)
    assert c.post(f"/api/docs/{document}/save", json={"content": current, "force": True}).status_code == 200
    response = c.post(f"/api/projects/{project}/proposals", json={"title": "Conflict", "files": [draft]})
    assert response.status_code == 409, response.text
    assert response.json()["detail"].startswith("Original passage changed")
    assert c.get(f"/api/docs/{document}").json()["content"] == current
    assert c.get(f"/api/projects/{project}/proposals").json()["packages"] == []


def test_reviewer_submission_is_isolated_and_owner_can_partially_accept(c):
    project, document = setup(c)
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/projects/{project}/members", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    package = submit(c, project, [document_change(document, "first old\nlast old\n", [("first old", "first new"), ("last old", "last new")])])
    assert c.get(f"/api/docs/{document}").json()["content"] == "first old\nlast old\n"
    assert accept(c, project, package).status_code == 403
    login(c, "alice")
    file = package["files"][0]
    response = accept(c, project, package, file_id=file["id"], change_id=file["changes"][0]["id"])
    assert response.status_code == 200, response.text
    partial = response.json()
    assert partial["accepted"] == 1
    assert len(partial["files"][0]["changes"]) == 1
    assert c.get(f"/api/docs/{document}").json()["content"] == "first new\nlast old\n"
    assert str(sync.room(document)["doc"].get("typst", type=Text)) == "first new\nlast old\n"
    assert accept(c, project, package).status_code == 409
    assert accept(c, project, partial, file_id=file["id"]).status_code == 200
    assert c.get(f"/api/docs/{document}").json()["content"] == "first new\nlast new\n"


def test_editor_corrects_proposal_but_cannot_delete_another_authors_package(c):
    project, document = setup(c, "old")
    package = submit(c, project, [document_change(document, "old", [("old", "proposed")])])
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/projects/{project}/members", json={"username": "bob", "role": "editor"})
    login(c, "bob")
    file = package["files"][0]
    file["content"] = "corrected"
    file["changes"][0]["new_string"] = "corrected"
    response = c.patch(f"/api/projects/{project}/proposals/{package['id']}", json={"title": "Correction", "revision": package["revision"], "files": [file]})
    assert response.status_code == 200, response.text
    assert c.get(f"/api/docs/{document}").json()["content"] == "old"
    assert c.delete(f"/api/projects/{project}/proposals/{package['id']}").status_code == 403
    assert accept(c, project, response.json()).status_code == 200
    assert c.get(f"/api/docs/{document}").json()["content"] == "corrected"


def test_added_attachment_dependencies_require_combined_acceptance(c):
    project, document = setup(c, "old")
    text = document_change(document, "old", [("old", '#image("plot.png")')])
    image = {"kind": "file", "doc_id": document, "path": "plot.png", "action": "add", "content": base64.b64encode(b"image").decode(), "binary": True}
    package = submit(c, project, [text, image])
    assert c.get(f"/api/docs/{document}/files/plot.png").status_code == 404
    assert accept(c, project, package, file_id=package["files"][0]["id"]).status_code == 409
    response = accept(c, project, package)
    assert response.status_code == 200, response.text
    assert c.get(f"/api/docs/{document}/files/plot.png").content == b"image"


def test_quota_failure_rolls_back_files_database_and_live_document(c, monkeypatch):
    project, document = setup(c, "old")
    text = document_change(document, "old", [("old", "new")])
    attachment = {"kind": "file", "doc_id": document, "path": "new.csv", "action": "add", "content": "a,b\n"}
    package = submit(c, project, [attachment, text])
    monkeypatch.setattr(quota, "check_quota", lambda *args, **kwargs: (_ for _ in ()).throw(HTTPException(413, "quota")))
    assert accept(c, project, package).status_code == 413
    assert c.get(f"/api/docs/{document}/files/new.csv").status_code == 404
    assert c.get(f"/api/docs/{document}").json()["content"] == "old"
    assert str(sync.room(document)["doc"].get("typst", type=Text)) == "old"
    saved = c.get(f"/api/projects/{project}/proposals/{package['id']}").json()
    assert saved["revision"] == package["revision"]


def test_file_acceptance_and_deleting_partial_package_preserve_accepted_changes(c):
    project, document = setup(c, "old")
    c.post(f"/api/projects/{project}/resources", json={"name": "data.csv", "content": "a,b\n1,2\n"})
    file = {"kind": "resource", "path": "data.csv", "action": "modify", "base": "a,b\n1,2\n", "content": "a,b\n3,4\n", "changes": [{"old_string": "1,2", "new_string": "3,4"}]}
    package = submit(c, project, [file, document_change(document, "old", [("old", "new")])])
    response = accept(c, project, package, file_id=package["files"][0]["id"])
    assert response.status_code == 200, response.text
    assert c.delete(f"/api/projects/{project}/proposals/{package['id']}").status_code == 200
    resources = c.get(f"/api/projects/{project}/resources").json()["resources"]
    assert next(r["content"] for r in resources if r["name"] == "data.csv") == "a,b\n3,4\n"
    assert c.get(f"/api/docs/{document}").json()["content"] == "old"


def test_delete_and_rename_file_proposals_are_not_applied_until_acceptance(c):
    project, document = setup(c)
    c.post(f"/api/projects/{project}/resources", json={"name": "unused.bib", "content": "old"})
    package = submit(c, project, [{"kind": "resource", "path": "unused.bib", "action": "rename", "target": "renamed.bib", "base": "old", "content": "old"}])
    assert accept(c, project, package).status_code == 200
    package = submit(c, project, [{"kind": "resource", "path": "renamed.bib", "action": "delete", "base": "old"}])
    assert accept(c, project, package).status_code == 200
    assert any(t["title"] == "renamed.bib" for t in c.get("/api/docs").json()["trash"])


def test_foreign_project_access_and_duplicate_file_ids_are_rejected(c):
    project, document = setup(c, "old")
    package = submit(c, project, [document_change(document, "old", [("old", "new")])])
    register_user(c, "eve")
    assert c.get(f"/api/projects/{project}/proposals").status_code == 404
    assert accept(c, project, package).status_code == 404
    login(c, "alice")
    file = document_change(document, "old", [("old", "new")])
    file["id"] = "duplicate"
    other = {"id": "duplicate", "kind": "resource", "path": "new.typ", "action": "add", "content": "text"}
    assert c.post(f"/api/projects/{project}/proposals", json={"title": "bad", "files": [file, other]}).status_code == 400


def test_account_rename_does_not_wipe_authored_packages(c):
    project, document = setup(c, "old")
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/projects/{project}/members", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    package = submit(c, project, [document_change(document, "old", [("old", "proposal")])])
    # Rename the author account: the package's FK cascaded to NOTHING before
    # the rename moved its author row (delete + insert, no ON UPDATE).
    assert c.post("/api/me/name", json={"name": "bobby", "password": "pass1234"}).status_code == 200
    login(c, "alice")
    rows = c.get(f"/api/projects/{project}/proposals").json()["packages"]
    assert [p["id"] for p in rows] == [package["id"]], rows
    assert rows[0]["author"] == "bobby"
    # It stays fully usable: the new owner can still accept it.
    assert accept(c, project, package).status_code == 200
    assert c.get(f"/api/docs/{document}").json()["content"] == "proposal"


def test_correction_can_discard_the_last_pending_change(c):
    project, document = setup(c, "old")
    package = submit(c, project, [document_change(document, "old", [("old", "new")])])
    response = c.patch(f"/api/projects/{project}/proposals/{package['id']}",
                       json={"title": "Correction", "revision": package["revision"], "files": []})
    assert response.status_code == 200, response.text
    saved = c.get(f"/api/projects/{project}/proposals/{package['id']}").json()
    assert saved["revision"] == package["revision"] + 1
    assert saved["files"] == []
    assert c.get(f"/api/docs/{document}").json()["content"] == "old"
    assert c.get(f"/api/projects/{project}/proposals").json()["packages"] == []


def test_partial_accept_keeps_unrebasable_sibling_marked_stale(c):
    project, document = setup(c, "alpha beta gamma\n")
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/projects/{project}/members", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    package = submit(c, project, [document_change(
        document, "alpha beta gamma\n",
        [("beta", "BETA"), ("gamma", "GAMMA")],
    )])
    login(c, "alice")
    # External edit removes the sibling's anchor BEFORE the accept.
    assert c.post(f"/api/docs/{document}/save", json={"content": "alpha beta\n", "force": True}).status_code == 200
    file = package["files"][0]
    response = accept(c, project, package, file_id=file["id"], change_id=file["changes"][0]["id"])
    assert response.status_code == 200, response.text
    partial = response.json()
    sibling = partial["files"][0]
    assert sibling["stale"] is True, sibling
    assert sibling["base"] == "alpha beta gamma\n"  # untouched original state
    assert sibling["content"] == "alpha beta GAMMA\n"
    assert [ch["old_string"] for ch in sibling["changes"]] == ["gamma"]
    # The selected change was applied, the stale sibling was not.
    assert c.get(f"/api/docs/{document}").json()["content"] == "alpha BETA\n"
    assert c.get(f"/api/docs/{document}").json()["content"] != "alpha BETA GAMMA\n"
    saved = c.get(f"/api/projects/{project}/proposals/{package['id']}").json()
    assert saved["files"][0]["stale"] is True
    assert saved["files"][0]["base"] == "alpha beta gamma\n"


def test_accept_rebases_still_matching_sibling_as_before(c):
    project, document = setup(c, "alpha beta gamma\n")
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/projects/{project}/members", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    package = submit(c, project, [document_change(
        document, "alpha beta gamma\n",
        [("beta", "BETA"), ("gamma", "GAMMA")],
    )])
    login(c, "alice")
    file = package["files"][0]
    response = accept(c, project, package, file_id=file["id"], change_id=file["changes"][0]["id"])
    assert response.status_code == 200, response.text
    partial = response.json()
    sibling = partial["files"][0]
    assert "stale" not in sibling, sibling
    assert sibling["base"] == "alpha BETA gamma\n"
    assert accept(c, project, partial, file_id=file["id"]).status_code == 200
    assert c.get(f"/api/docs/{document}").json()["content"] == "alpha BETA GAMMA\n"


def test_dependencies_trust_empty_live_room_over_stale_db_text(c, monkeypatch):
    project, document = setup(c, '#image("plot.png")\n')
    register_user(c, "bob")
    login(c, "alice")
    plotdata = b"plotdata-bytes"
    assert c.post(f"/api/docs/{document}/files", files={"f": ("plot.png", plotdata)}).status_code == 200
    c.post(f"/api/projects/{project}/members", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    package = submit(c, project, [{
        "kind": "file", "doc_id": document, "path": "plot.png",
        "action": "delete", "base": plotdata.decode(),
    }])
    # The live room reports EMPTY text while the DB row is stale and still
    # references plot.png: falling back to the stale text would let the
    # document ref check block this unrelated delete with a 409.
    monkeypatch.setattr(sync, "room_text", lambda doc_id: "" if doc_id == document else None)
    login(c, "alice")
    response = accept(c, project, package)
    assert response.status_code == 200, response.text
    assert c.get(f"/api/docs/{document}/files/plot.png").status_code == 404


def test_proposal_cannot_add_case_variant_of_existing_resource(c):
    project, document = setup(c, "old")
    assert c.post(f"/api/projects/{project}/resources", json={"name": "data.csv", "content": "original"}).status_code == 200
    package = submit(c, project, [{"kind": "resource", "path": "DATA.csv", "action": "add", "content": "proposal"}])
    response = accept(c, project, package)
    assert response.status_code == 409, response.text
    rows = c.get(f"/api/projects/{project}/resources").json()["resources"]
    assert [(row["name"], row["content"]) for row in rows] == [("data.csv", "original")]


def test_failed_undo_snapshot_cannot_desync_a_committed_accept(c, monkeypatch):
    from backend.services import snapshots

    project, document = setup(c, "old")
    package = submit(c, project, [document_change(document, "old", [("old", "new")])])
    monkeypatch.setattr(snapshots, "auto_snap", lambda *a, **kw: (_ for _ in ()).throw(sqlite3.OperationalError("busy")))
    response = accept(c, project, package)
    assert response.status_code == 200, response.text
    assert c.get(f"/api/docs/{document}").json()["content"] == "new"
    assert str(sync.room(document)["doc"].get("typst", type=Text)) == "new"
