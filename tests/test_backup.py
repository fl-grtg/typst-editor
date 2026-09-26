import io
import zipfile

from conftest import login, make_doc, register_user


def test_export_zip(c):
    register_user(c, "alice")
    make_doc(c, "Backup", content="inhalt")
    r = c.get("/api/export.zip")
    assert r.status_code == 200
    assert r.content[:2] == b"PK"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert any(n.endswith(".typ") for n in names)
    assert any("Backup" in n for n in names)


def test_export_only_own(c):
    # Design: kein 403 — jeder bekommt nur seine Docs (fremde fehlen).
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    make_doc(c, "AlicesDoc", content="a")
    login(c, "bob")
    r = c.get("/api/export.zip")
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert not any("AlicesDoc" in n for n in names)
