import io
import zipfile

import pytest
from conftest import make_doc, register_user


def bundle(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def import_zip(c, data, title="Imported", folder=""):
    return c.post("/api/docs/import-zip", files={"f": ("source.zip", data, "application/zip")}, data={"title": title, "folder": folder})


def test_export_import_preserves_local_files_and_localizes_global_modules(c):
    register_user(c, "zipuser")
    assert c.post("/api/templates", json={"name": "layout.typ", "content": '= Global layout'}).status_code == 200
    assert c.post("/api/templates", json={"name": "values.json", "content": '{"amount":12}'}).status_code == 200
    main = '#include "layout.typ"\n#json("values.json").amount\n#include "chapters/chapter.typ"'
    did = make_doc(c, title="Original", content=main)
    assert c.post(f"/api/docs/{did}/files/chapters/chapter.typ/text", json={"content": "Nested chapter"}).status_code == 200
    exported = c.post(f"/api/docs/{did}/export?format=zip")
    assert exported.status_code == 200
    result = import_zip(c, exported.content, folder="Archive")
    assert result.status_code == 200, result.text
    imported = result.json()["id"]
    document = c.get(f"/api/docs/{imported}").json()
    assert document["content"] == main
    assert document["folder"] == ""
    assert c.get(f"/api/projects/{document['project_id']}").json()["title"] == "Archive"
    for name, expected in [("layout.typ", '= Global layout'), ("values.json", '{"amount":12}'), ("chapters/chapter.typ", "Nested chapter")]:
        assert c.get(f"/api/docs/{imported}/files/{name}/text").json()["content"] == expected
    assert len(c.get("/api/templates").json()["templates"]) == 2
    # Import is self-contained even when the global shelf changes later.
    assert c.delete("/api/templates/layout.typ").status_code == 200
    assert c.get(f"/api/docs/{imported}/files/layout.typ/text").json()["content"] == '= Global layout'


@pytest.mark.parametrize("entries", [
    [("a.typ", "One"), ("b.typ", "Two")],
    [("main.typ", "Main"), ("../bad.typ", "Bad")],
    [("main.typ", "Main"), ("/bad.typ", "Bad")],
    [("main.typ", "Main"), ("chapter.typ", "A"), ("CHAPTER.typ", "B")],
    [("main.typ", b"\xff")],
])
def test_invalid_archives_do_not_create_documents(c, entries):
    register_user(c, "zipbad")
    before = c.get("/api/docs").json()["own"]
    result = import_zip(c, bundle(entries))
    assert result.status_code == 400
    assert c.get("/api/docs").json()["own"] == before


def test_zip_can_have_one_enclosing_folder_and_conflicts_do_not_overwrite(c):
    register_user(c, "zipfolder")
    count = len(c.get("/api/docs").json()["own"])
    data = bundle([("Project/main.typ", '#include "part.typ"'), ("Project/part.typ", "Part")])
    first = import_zip(c, data)
    assert first.status_code == 200
    assert c.get(f"/api/docs/{first.json()['id']}/files/part.typ/text").json()["content"] == "Part"
    second = import_zip(c, data)
    assert second.status_code == 200
    assert second.json()["id"] != first.json()["id"]
    assert len(c.get("/api/docs").json()["own"]) == count + 2


def test_zip_import_rolls_back_when_storage_write_fails(c, monkeypatch):
    from backend import deps
    from backend.services.projectzip import store

    register_user(c, "zipfail")
    before = c.get("/api/docs").json()["own"]
    original = store.put

    def fail_second(did, name, data):
        if name == "b.typ":
            raise OSError("Disk full")
        return original(did, name, data)

    monkeypatch.setattr(store, "put", fail_second)
    with pytest.raises(OSError):
        import_zip(c, bundle([("main.typ", '#include "a.typ"\n#include "b.typ"'), ("a.typ", "A"), ("b.typ", "B")]))
    assert c.get("/api/docs").json()["own"] == before
    assert not list(deps.get_files_dir().glob("d_*"))


def test_source_zip_preserves_generic_binary_attachment(c):
    register_user(c, "zipgeneric")
    result = import_zip(c, bundle([("main.typ", "Main"), ("assets/data.bin", b"\x00\xff")]))
    assert result.status_code == 200, result.text
    did = result.json()["id"]
    response = c.get(f"/api/docs/{did}/files/assets/data.bin")
    assert response.status_code == 200
    assert response.content == b"\x00\xff"
    assert response.headers["content-disposition"].startswith("attachment;")


def test_standalone_import_keeps_a_free_form_folder_name(c):
    register_user(c, "zipfolder")
    result = import_zip(c, bundle([("main.typ", "= Hi")]), folder="Übung 1")
    assert result.status_code == 200, result.text
    project = c.get(f"/api/docs/{result.json()['id']}").json()["project_id"]
    assert c.get(f"/api/projects/{project}").json()["title"] == "Übung 1"


def test_zip_preview_suggests_the_root_and_import_takes_a_chosen_document(c):
    register_user(c, "zipchoose")
    data = bundle([("book.typ", '#include "ch1.typ"'), ("ch1.typ", "One"), ("notes.typ", "Notes")])
    preview = c.post("/api/zip-preview", files={"f": ("s.zip", data, "application/zip")}).json()
    assert preview["entries"] == ["book.typ", "ch1.typ", "notes.typ"] and preview["suggested"] == ""
    assert import_zip(c, data).status_code == 400
    result = import_zip(c, data, title="", folder="Pick")
    assert result.status_code == 400
    r = c.post("/api/docs/import-zip", files={"f": ("s.zip", data, "application/zip")}, data={"entry": "notes.typ"})
    assert r.status_code == 200, r.text
    assert c.get(f"/api/docs/{r.json()['id']}").json()["title"] == "notes"
    only = bundle([("main.typ", "x")])
    assert c.post("/api/zip-preview", files={"f": ("s.zip", only, "application/zip")}).json()["suggested"] == "main.typ"
