from conftest import login, make_doc, register_user

from backend import db, deps
from backend.services import docfiles


def _up(c, did, name, data=b"abc"):
    return c.post(f"/api/docs/{did}/files", files={"f": (name, data)})


def test_upload_list_get_delete(c):
    register_user(c, "alice")
    did = make_doc(c, "Dateien")
    assert _up(c, did, "bild.png").status_code == 200
    names = [f["name"] for f in c.get(f"/api/docs/{did}/files").json()["files"]]
    assert "bild.png" in names
    assert c.get(f"/api/docs/{did}/files/bild.png").status_code == 200
    assert c.delete(f"/api/docs/{did}/files/bild.png").status_code == 200
    assert c.get(f"/api/docs/{did}/files/bild.png").status_code == 404


def test_upload_rejects_traversal_and_accepts_generic_attachments(c):
    register_user(c, "alice")
    did = make_doc(c, "Dateien2")
    assert _up(c, did, "../../evil.sh").status_code == 400
    assert _up(c, did, "tool.exe", b"x").status_code == 200
    response = c.get(f"/api/docs/{did}/files/tool.exe")
    assert response.content == b"x"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_upload_over_10mb_400(c):
    register_user(c, "alice")
    did = make_doc(c, "Dateien3")
    assert _up(c, did, "gross.png", b"x" * (10 * 1024 * 1024 + 1)).status_code == 400


def test_svg_attachment(c):
    register_user(c, "alice")
    did = make_doc(c, "Dateien4")
    assert _up(c, did, "grafik.svg", b"<svg></svg>").status_code == 200
    r = c.get(f"/api/docs/{did}/files/grafik.svg")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")


def test_reviewer_upload_403(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Dateien5")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    assert _up(c, did, "x.png").status_code == 403


def test_text_tab(c):
    register_user(c, "alice")
    did = make_doc(c, "Dateien6")
    assert c.post(f"/api/docs/{did}/files/notizen.typ/text", json={"content": "hallo"}).status_code == 200
    assert c.get(f"/api/docs/{did}/files/notizen.typ/text").json()["content"] == "hallo"
    assert c.post(f"/api/docs/{did}/files/bild.png/text", json={"content": "x"}).status_code == 400


def test_write_leaves_no_tmp(c):
    register_user(c, "alice")
    did = make_doc(c, "DateienTmp")
    assert _up(c, did, "bild.png", b"abc").status_code == 200
    assert c.post(f"/api/docs/{did}/files/notizen.typ/text",
                 json={"content": "hallo"}).status_code == 200
    d = deps.get_files_dir() / did
    assert list(d.glob("*.tmp.*")) == []
    names = [f["name"] for f in c.get(f"/api/docs/{did}/files").json()["files"]]
    assert "bild.png" in names
    assert "notizen.typ" in names
    assert not any(".tmp." in n for n in names)


def test_missing_file_cleanup_rechecks_write_permission(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Missing attachment")
    assert _up(c, did, "gone.png").status_code == 200
    docfiles.store.delete(did, "gone.png")
    monkeypatch.setattr(deps, "_tx_role", lambda *args: "reviewer")
    assert c.delete(f"/api/docs/{did}/files/gone.png").status_code == 403
    con = db.connect()
    try:
        assert con.execute("SELECT 1 FROM files WHERE doc_id=? AND path=?", (did, "gone.png")).fetchone()
    finally:
        con.close()


def _trash_for_doc(c, did):
    return [t for t in c.get("/api/docs").json()["trash"] if t.get("doc_id") == did and t.get("kind") == "file"]


def test_failed_delete_rollback_only_drops_its_own_trash_entry(c, monkeypatch):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "RollbackEingrenzung")
    # two earlier trash-cycles leave two same-name entries with older copies
    assert _up(c, did, "data.csv", b"first").status_code == 200
    assert c.delete(f"/api/docs/{did}/files/data.csv").status_code == 200
    assert _up(c, did, "data.csv", b"second").status_code == 200
    assert c.delete(f"/api/docs/{did}/files/data.csv").status_code == 200
    before = sorted(t["id"] for t in _trash_for_doc(c, did))
    assert len(before) == 2
    assert _up(c, did, "data.csv", b"third").status_code == 200
    # FS delete "fails" on the third cycle: the rollback must delete ONLY the
    # trash row it just created (older same-name copies stay intact)
    monkeypatch.setattr(docfiles.store, "delete", lambda doc_id, path: False)
    assert c.delete(f"/api/docs/{did}/files/data.csv").status_code == 500
    after = sorted(t["id"] for t in _trash_for_doc(c, did))
    assert after == before
    # sync_doc_files ran outside the tx: the live file is visible again
    assert c.get(f"/api/docs/{did}/files/data.csv").content == b"third"
    names = [f["name"] for f in c.get(f"/api/docs/{did}/files").json()["files"]]
    assert "data.csv" in names
