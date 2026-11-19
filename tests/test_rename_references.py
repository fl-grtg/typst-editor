"""Renaming or moving project entries can rewrite the Typst paths that point at them."""
from conftest import register_user

from backend.services import ref_rewrite


def make(c, main):
    register_user(c, "alice")
    did = c.post("/api/docs/create", json={"title": "Main", "content": main}).json()["id"]
    pid = c.get(f"/api/docs/{did}").json()["project_id"]
    return pid, did


def upload(c, did, name, data=b"png"):
    assert c.post(f"/api/docs/{did}/files", files={"f": (name, data, "application/octet-stream")}).status_code == 200


def text_file(c, did, name, content):
    assert c.post(f"/api/docs/{did}/files/{name}/text", json={"content": content}).status_code == 200


def main_text(c, did):
    return c.get(f"/api/docs/{did}").json()["content"]


def rename(c, pid, name, target, doc_id="", update=True):
    body = {"name": name, "target": target, "doc_id": doc_id}
    preview = c.post(f"/api/projects/{pid}/rename-entry-preview", json=body)
    assert preview.status_code == 200, preview.text
    pv = preview.json()
    r = c.post(f"/api/projects/{pid}/rename-entry", json={**body, "target": pv["name"], "version": pv["version"], "update_references": update})
    assert r.status_code == 200, r.text
    return pv, r.json()


def test_rewrite_keeps_style_and_ignores_unknown_paths():
    moves = {"img/a.png": "pics/a.png"}

    def look(p):
        return moves.get(p, p) if p in {"img/a.png", "other.png"} else None
    text = '#image("img/a.png") #image("/img/a.png") #image("other.png") #image("missing.png") "img/a.png"'
    edits = ref_rewrite.rewrite(text, "main.typ", "main.typ", look)
    assert ref_rewrite.apply_edits(text, [e for e, _ in edits]) == (
        '#image("pics/a.png") #image("/pics/a.png") #image("other.png") #image("missing.png") "pics/a.png"')
    # a moved referrer fixes its own relative paths, even when the target stays
    edits = ref_rewrite.rewrite('#image("../other.png")', "ch/x.typ", "a/b/x.typ", look)
    assert [e[2] for e, _ in edits] == ["../../other.png"]
    assert ref_rewrite.rewrite('#image("./img/a.png")', "main.typ", "main.typ", look)[0][0][2] == "./pics/a.png"


def test_file_rename_previews_and_updates_main_and_chapters(c):
    pid, did = make(c, '#image("logo.png")\n#include "ch/one.typ"\nÄ😀 "logo.png"')
    upload(c, did, "logo.png")
    text_file(c, did, "ch/one.typ", '#image("../logo.png")\n#image("/logo.png")')
    pv, res = rename(c, pid, "logo.png", "img/brand.png", did)
    assert {(ch["path"], ch["old"], ch["new"]) for ch in pv["changes"]} == {
        ("main.typ", "logo.png", "img/brand.png"), ("ch/one.typ", "../logo.png", "../img/brand.png"),
        ("ch/one.typ", "/logo.png", "/img/brand.png")}
    assert res["updated"] == 4
    assert main_text(c, did) == '#image("img/brand.png")\n#include "ch/one.typ"\nÄ😀 "img/brand.png"'
    assert c.get(f"/api/docs/{did}/files/ch/one.typ/text").json()["content"] == '#image("../img/brand.png")\n#image("/img/brand.png")'


def test_rename_without_update_keeps_references(c):
    pid, did = make(c, '#image("logo.png")')
    upload(c, did, "logo.png")
    _, res = rename(c, pid, "logo.png", "brand.png", did, update=False)
    assert res["updated"] == 0
    assert main_text(c, did) == '#image("logo.png")'


def test_module_rename_updates_every_document_and_modules(c):
    pid, did = make(c, '#import "lib/style.typ": *')
    other = c.post(f"/api/projects/{pid}/docs", json={"title": "Two", "content": '#import "/lib/style.typ": x'}).json()["id"]
    c.post(f"/api/projects/{pid}/resources", json={"name": "lib/style.typ", "content": '#import "colors.typ": *'})
    c.post(f"/api/projects/{pid}/resources", json={"name": "lib/colors.typ", "content": ""})
    c.post(f"/api/projects/{pid}/resources", json={"name": "lib/all.typ", "content": '#import "style.typ"'})
    _, res = rename(c, pid, "lib/style.typ", "theme/style.typ")
    assert res["updated"] == 4
    assert main_text(c, did) == '#import "theme/style.typ": *'
    assert main_text(c, other) == '#import "/theme/style.typ": x'
    lib = {r["name"]: r["content"] for r in c.get(f"/api/projects/{pid}/resources").json()["resources"]}
    assert lib["lib/all.typ"] == '#import "../theme/style.typ"'
    assert lib["theme/style.typ"] == '#import "../lib/colors.typ": *'  # the moved module keeps its own imports working


def test_local_file_shadows_module_of_same_name(c):
    pid, did = make(c, '#import "util.typ": *')
    text_file(c, did, "util.typ", "")
    c.post(f"/api/projects/{pid}/resources", json={"name": "util.typ", "content": ""})
    pv, res = rename(c, pid, "util.typ", "tools.typ")  # the module: this document uses its own file
    assert pv["changes"] == [] and res["updated"] == 0
    assert main_text(c, did) == '#import "util.typ": *'


def test_folder_rename_preview_and_rewrite(c):
    pid, did = make(c, '#image("img/a.png")\n#include "img/cap.typ"')
    upload(c, did, "img/a.png")
    text_file(c, did, "img/cap.typ", '#image("a.png")')
    body = {"path": "img", "target": "media/img"}
    pv = c.post(f"/api/projects/{pid}/folders/rename-preview", json=body)
    assert pv.status_code == 200, pv.text
    assert sorted(ch["new"] for ch in pv.json()["changes"]) == ["media/img/a.png", "media/img/cap.typ"]
    r = c.post(f"/api/projects/{pid}/folders/rename", json={**body, "update_references": True})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2 and "_moves" not in r.json()
    assert main_text(c, did) == '#image("media/img/a.png")\n#include "media/img/cap.typ"'
    assert c.get(f"/api/docs/{did}/files/media/img/cap.typ/text").json()["content"] == '#image("a.png")'


def test_folder_rename_default_does_not_rewrite(c):
    pid, did = make(c, '#image("img/a.png")')
    upload(c, did, "img/a.png")
    r = c.post(f"/api/projects/{pid}/folders/rename", json={"path": "img", "target": "pics"})
    assert r.status_code == 200 and r.json()["updated"] == 0
    assert main_text(c, did) == '#image("img/a.png")'


def test_live_room_gets_targeted_edits(c):
    import asyncio

    from backend import sync

    pid, did = make(c, 'ä😀 #image("logo.png") tail')
    upload(c, did, "logo.png")
    sync.room(did)
    try:
        before = sync.room_text(did)
        assert before == 'ä😀 #image("logo.png") tail'
        _, res = rename(c, pid, "logo.png", "img/logo.png", did)
        assert res["updated"] == 1
        assert sync.room_text(did) == 'ä😀 #image("img/logo.png") tail'
        assert main_text(c, did) == 'ä😀 #image("img/logo.png") tail'  # persisted, not only in memory
        assert asyncio.run(sync.patch_text(did, lambda text: [])) == 0
    finally:
        sync.rooms.pop(did, None)
