from conftest import login, register_user

from backend import db
from backend.services.notifications import create_notification, unread_count


def test_owner_rename_and_account_deletion_preserve_project_integrity(c):
    register_user(c, "alice")
    c.post("/api/folders", json={"folder": "Team"})
    p = c.post("/api/projects/preview", json={"folder": "Team"}).json()
    pid = c.post("/api/projects/convert", json={"folder": "Team", "preview": p["preview"]}).json()["id"]
    did = c.post(f"/api/projects/{pid}/docs", json={"title": "Report"}).json()["id"]
    c.post(f"/api/projects/{pid}/resources", json={"name": "module.typ", "content": "Shared"})
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/projects/{pid}/members", json={"username": "bob", "role": "editor"})
    nid = create_notification("alice", "system", did, "Keep inbox")
    renamed = c.post("/api/me/name", json={"name": "alice_new", "password": "pass1234"})
    assert renamed.status_code == 200, renamed.text
    login(c, "alice_new")
    assert unread_count("alice_new") == 1
    assert unread_count("alice") == 0
    with db.tx() as con:
        assert con.execute("SELECT recipient FROM notifications WHERE id=?", (nid,)).fetchone()[0] == "alice_new"
    assert c.get(f"/api/projects/{pid}").json()["owner"] == "alice_new"
    assert c.get(f"/api/docs/{did}").json()["owner"] == "alice_new"
    deleted = c.post("/api/me/delete", json={"password": "pass1234"})
    assert deleted.status_code == 200, deleted.text
    con = db.connect()
    try:
        assert con.execute("SELECT COUNT(*) FROM projects WHERE owner='alice_new'").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM project_resources").fetchone()[0] == 0
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        con.close()


def test_renamed_author_keeps_checkpoint_rights(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = c.post("/api/docs/create", json={"title": "Doc"}).json()["id"]
    pid = c.get(f"/api/docs/{did}").json()["project_id"]
    assert c.post(f"/api/projects/{pid}/members", json={"username": "bob", "role": "editor"}).status_code == 200
    login(c, "bob")
    sid = c.post(f"/api/projects/{pid}/snapshots", json={"label": "Bob base"}).json()["id"]
    assert c.post("/api/me/name", json={"name": "bobby", "password": "pass1234"}).status_code == 200
    login(c, "bobby")
    listed = c.get(f"/api/projects/{pid}/snapshots").json()["snapshots"]
    assert next(s["author"] for s in listed if s["id"] == sid) == "bobby"
    assert c.delete(f"/api/projects/{pid}/snapshots/{sid}").status_code == 200
