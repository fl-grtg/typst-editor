from conftest import login, make_doc, register_user

from backend import deps


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


def test_upload_rejected(c):
    register_user(c, "alice")
    did = make_doc(c, "Dateien2")
    assert _up(c, did, "../../evil.sh").status_code == 400
    assert _up(c, did, "tool.exe", b"x").status_code == 400


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
