"""Round 4 fixes: checkpoint retention (#5), stale selections instead of hard
409 (#4), project-unique entry names (#7) and the open-packages summary (#6)."""
import datetime
import hashlib
import io
import zipfile

from conftest import login, make_doc, register_user

from backend import constants, db
from backend.services import project_history


def project(c, content="base"):
    """Registers alice, creates doc "Round4"; returns (project_id, doc_id)."""
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Round4", content)
    pid = c.get(f"/api/docs/{did}").json()["project_id"]
    return pid, did


def member(c, pid, username, role="reviewer"):
    """The project owner (already logged in) adds a member."""
    r = c.post(f"/api/projects/{pid}/members", json={"username": username, "role": role})
    assert r.status_code == 200, r.text


# --- #5 smart checkpoint retention ------------------------------------------

def _snapshots(pid):
    with db.tx() as con:
        return con.execute(
            "SELECT id,kind,label,created_at FROM project_snapshots WHERE project_id=? "
            "ORDER BY created_at DESC,rowid DESC", (pid,)).fetchall()


def test_auto_checkpoints_stay_bounded_and_manuals_survive(c, monkeypatch):
    pid, _did = project(c)
    assert c.post(f"/api/projects/{pid}/snapshots", json={"label": "Manual"}).status_code == 200
    assert c.post(f"/api/projects/{pid}/snapshots", json={}).status_code == 200  # UI manual save (empty label)
    base = _snapshots(pid)
    manuals = {r["id"] for r in base if r["kind"] == "manual"}
    assert len(base) == 3 and len(manuals) == 2  # creation anchor (auto) + both manuals
    monkeypatch.setattr(constants, "SNAP_EVERY", 0)  # auto() re-imports SNAP_EVERY per call
    for _ in range(15):
        project_history.auto(pid)
    rows = _snapshots(pid)
    autos = [r for r in rows if r["kind"] == "auto"]
    assert {r["id"] for r in rows if r["kind"] == "manual"} == manuals  # never pruned
    assert len(autos) <= constants.AUTO_SNAP_KEEP + 1 + constants.AUTO_SNAP_KEEP_WEEKS
    assert len(autos) >= constants.AUTO_SNAP_KEEP  # auto() really saved, not only warned


def test_creation_anchor_and_newest_auto_survive_pruning(c, monkeypatch):
    pid, did = project(c)
    anchor = _snapshots(pid)[0]["id"]  # the one row so far: the creation checkpoint
    monkeypatch.setattr(constants, "SNAP_EVERY", 0)
    for _ in range(12):
        project_history.auto(pid)
    rows = _snapshots(pid)
    assert anchor in {r["id"] for r in rows}
    newest = rows[0]
    assert newest["kind"] == "auto"
    # Restoring the newest kept checkpoint keeps working after pruning.
    response = c.post(f"/api/projects/{pid}/snapshots/{newest['id']}/restore", json={})
    assert response.status_code == 200, response.text
    assert c.get(f"/api/docs/{did}").json()["content"] == "base"


def test_weekly_decay_keeps_one_per_week_within_the_window(c):
    pid, _did = project(c)
    state = {"documents": [], "resources": {}}
    with db.tx() as con:
        project_history.save(con, pid, state, label="Mine", kind="manual")
        now = datetime.datetime.now(datetime.UTC)
        # Oldest first, so every intermediate _retain keeps by the cap window.
        ages = [9, 8, 4, 3, 2, 1, 0, 0, 0, 0, 0, 0, 0]
        for age in ages:
            sid = project_history.save(con, pid, state, kind="auto")
            con.execute("UPDATE project_snapshots SET created_at=? WHERE id=?",
                        ((now - datetime.timedelta(weeks=age)).isoformat(), sid))
    with db.tx() as con:
        project_history.save(con, pid, state, kind="auto")  # next save runs retention
    now = datetime.datetime.now(datetime.UTC)  # as-of moment after the trigger save
    rows = _snapshots(pid)
    manuals = [r for r in rows if r["kind"] == "manual"]
    assert len(manuals) == 1  # manual checkpoints are never pruned
    autos = [r for r in rows if r["kind"] == "auto"]
    assert len(autos) <= constants.AUTO_SNAP_KEEP + constants.AUTO_SNAP_KEEP_WEEKS
    weeks = sorted((now - datetime.datetime.fromisoformat(r["created_at"])).days // 7
                   for r in autos)
    # week-8 rows are pruned; the week-9 row stays as the project's oldest row
    # (creation-anchor rule); week 0 rides in the newest-10 window.
    assert weeks == [0] * 9 + [1, 2, 3, 4, 9]


def test_retention_frees_snapshot_bytes(c, monkeypatch):
    from backend.services import quota
    pid, _did = project(c)
    monkeypatch.setattr(constants, "SNAP_EVERY", 0)
    for _ in range(12):
        project_history.auto(pid)
    before = quota.user_bytes("alice")
    project_history.auto(pid)  # every save past the cap prunes older week-0 autos
    assert quota.user_bytes("alice") <= before


# --- #4 drift handling on proposal accept -----------------------------------

def package(c, pid, did, base, changes, title="Review"):
    text = base
    for old, new in changes:
        text = text.replace(old, new, 1)
    body = {"title": title, "files": [{
        "kind": "document", "doc_id": did, "path": "main.typ", "action": "modify",
        "base": base, "content": text,
        "changes": [{"old_string": o, "new_string": n} for o, n in changes],
    }]}
    response = c.post(f"/api/projects/{pid}/proposals", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_selected_drift_marks_stale_instead_of_409(c):
    register_user(c, "bob")
    pid, did = project(c, "alpha beta gamma\n")  # logged in as alice (owner)
    member(c, pid, "bob", "reviewer")
    login(c, "bob")
    pack = package(c, pid, did, "alpha beta gamma\n", [("beta", "BETA")])
    login(c, "alice")
    # drift: the passage disappears BEFORE the accept
    r = c.post(f"/api/docs/{did}/save", json={"content": "alpha gamma\n", "force": True})
    assert r.status_code == 200, r.text
    file = pack["files"][0]
    response = c.post(f"/api/projects/{pid}/proposals/{pack['id']}/accept",
                      json={"revision": pack["revision"], "file_id": file["id"],
                            "change_id": file["changes"][0]["id"]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["files"][0]["stale"] is True
    assert result["files"][0]["changes"] == file["changes"]
    saved = c.get(f"/api/projects/{pid}/proposals/{pack['id']}").json()
    assert saved["files"][0]["stale"] is True
    assert c.get(f"/api/docs/{did}").json()["content"] == "alpha gamma\n"


def test_whole_package_accept_stays_hard_409_with_occurrence_hint(c):
    register_user(c, "bob")
    pid, did = project(c, "alpha beta tail\n")
    member(c, pid, "bob", "reviewer")
    login(c, "bob")
    pack = package(c, pid, did, "alpha beta tail\n", [("beta", "BETA"), ("tail", "TAIL")])
    login(c, "alice")
    # drift: the passage becomes ambiguous for a whole-package accept
    r = c.post(f"/api/docs/{did}/save", json={"content": "beta tail beta\n", "force": True})
    assert r.status_code == 200, r.text
    response = c.post(f"/api/projects/{pid}/proposals/{pack['id']}/accept",
                      json={"revision": pack["revision"]})
    assert response.status_code == 409
    assert "2 occurrences" in response.json()["detail"], response.text
    assert c.get(f"/api/docs/{did}").json()["content"] == "beta tail beta\n"


def test_draft_validation_reports_zero_occurrences(c):
    pid, did = project(c)
    response = c.post(f"/api/projects/{pid}/proposals", json={"title": "Stale draft", "files": [{
        "kind": "document", "doc_id": did, "path": "main.typ", "action": "modify",
        "base": "base", "content": "gone", "changes": [{"old_string": "vanished", "new_string": "gone"}],
    }]})
    assert response.status_code == 409
    assert "0 occurrences" in response.json()["detail"], response.text


# --- #7 project-wide unique entry names --------------------------------------

def test_filename_unique_across_sibling_docs(c):
    pid, did = project(c)
    other = c.post(f"/api/projects/{pid}/docs", json={"title": "Second"}).json()["id"]
    assert c.post(f"/api/docs/{did}/files", files={"f": ("fdgbdf.txt", b"x")}).status_code == 200
    assert c.post(f"/api/docs/{other}/files", files={"f": ("fdgbdf.txt", b"x")}).status_code == 409
    assert c.post(f"/api/docs/{other}/files", files={"f": ("FDGBDF.txt", b"x")}).status_code == 409
    # replacing the entry in its own doc never regresses
    assert c.post(f"/api/docs/{did}/files", files={"f": ("fdgbdf.txt", b"y")}).status_code == 200


def test_text_file_create_collision_and_rename(c):
    pid, did = project(c)
    other = c.post(f"/api/projects/{pid}/docs", json={"title": "Second"}).json()["id"]
    assert c.post(f"/api/docs/{did}/files/a.csv/text", json={"content": "1,2"}).status_code == 200
    assert c.post(f"/api/docs/{other}/files/A.CSV/text", json={"content": "x"}).status_code == 409
    c.post(f"/api/docs/{other}/files/new.csv/text", json={"content": "z"})
    # renaming a doc entry needs the sha256 version guard (optimistic lock)
    version = hashlib.sha256(b"1,2").hexdigest()
    r = c.post(f"/api/projects/{pid}/rename-entry",
               json={"name": "a.csv", "target": "b.csv", "doc_id": did, "version": version})
    assert r.status_code == 200, r.text
    # renaming onto a sibling doc's live name is a real collision (409 even
    # though the version string is wrong yet - the name check fires first)
    assert c.post(f"/api/projects/{pid}/rename-entry",
                  json={"name": "b.csv", "target": "new.csv", "doc_id": did,
                        "version": "x"}).status_code == 409


def test_module_names_unique_case_insensitively(c):
    pid, _did = project(c)
    assert c.post(f"/api/projects/{pid}/resources", json={"name": "module.typ", "content": "a"}).status_code == 200
    assert c.post(f"/api/projects/{pid}/resources", json={"name": "Module.typ", "content": "b"}).status_code == 409
    assert c.post(f"/api/projects/{pid}/resources", json={"name": "module.typ", "content": "c"}).status_code == 409
    # updating the existing row without a fresh version stays rejected as before
    c.post(f"/api/projects/{pid}/resources", json={"name": "other.typ", "content": "d"})
    assert c.post(f"/api/projects/{pid}/rename-entry",
                  json={"name": "other.typ", "target": "MODULE.typ"}).status_code == 409


def test_zip_import_respects_sibling_doc_names(c):
    pid, did = project(c)
    assert c.post(f"/api/docs/{did}/files", files={"f": ("im.png", b"img")}).status_code == 200
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("main.typ", "x")
        archive.writestr("IM.PNG", b"other")
    response = c.post(f"/api/projects/{pid}/import-zip",
                      data={"title": "Imported"}, files={"f": ("src.zip", data.getvalue(), "application/zip")})
    assert response.status_code == 409, response.text


# Trash restore keeps its own collision flow (reference:
# tests/test_project_transfer.py::test_document_names_are_project_local_and_restore_never_overwrites).


# --- #6 open review packages in the topbar summary ---------------------------

def proj_package(c, pid, title="Review", old="x", new="y", content="x"):
    did = c.get(f"/api/projects/{pid}").json()["documents"][0]["id"]
    body = {"kind": "document", "doc_id": did, "path": "main.typ", "action": "modify",
            "base": content, "content": content.replace(old, new),
            "changes": [{"old_string": old, "new_string": new}]}
    response = c.post(f"/api/projects/{pid}/proposals", json={"title": title, "files": [body]})
    assert response.status_code == 200, response.text
    return response.json()


def test_summary_lists_open_packages_of_others(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "bob")
    did = make_doc(c, "Team", "x")
    pid = c.get(f"/api/docs/{did}").json()["project_id"]
    member(c, pid, "alice", "reviewer")
    authored = proj_package(c, pid)
    # the author never sees their own package on the summary
    mine = c.get("/api/notifications/summary").json()
    assert mine["packages"] == [] and mine["package_total"] == 0
    login(c, "alice")
    extra = proj_package(c, pid, title="Second")
    # reviewers see the open packages of the other author (author filter)
    summary = c.get("/api/notifications/summary").json()
    assert [p["id"] for p in summary["packages"]] == [authored["id"]]
    assert summary["package_total"] == 1
    first = summary["packages"][0]
    assert {"project", "id", "title", "author", "updated_at"} <= set(first)
    assert first["project"] == pid and first["author"] == "bob"
    # a non-member stays empty even with a session
    register_user(c, "eve")
    login(c, "eve")
    empty = c.get("/api/notifications/summary").json()
    assert empty["packages"] == [] and empty["package_total"] == 0
    # acceptance empties the package; the accepted side then drops off the summary
    login(c, "bob")
    r = c.post(f"/api/projects/{pid}/proposals/{extra['id']}/accept",
               json={"revision": extra["revision"]})
    assert r.status_code == 200, r.text
    summary = c.get("/api/notifications/summary").json()
    assert summary["packages"] == [] and summary["package_total"] == 0


def test_summary_rejects_anonymous(c):
    assert c.get("/api/notifications/summary").status_code == 401
