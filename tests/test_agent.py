"""Agent tools over the real Streamable-HTTP protocol: paths, writes, edits, moves, trash, search."""
import base64
import json
import shutil

import pytest
from conftest import login, register_user

from backend import sync


def _sse(text):
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(f"no SSE payload in: {text[:500]!r}")


class Agent:
    def __init__(self, c, key):
        self.c, self.key, self.n = c, key, 0

    def raw(self, name, **args):
        self.n += 1
        r = self.c.post("/mcp", json={"jsonrpc": "2.0", "id": self.n, "method": "tools/call", "params": {"name": name, "arguments": args}},
                        headers={"Authorization": f"Bearer {self.key}", "Accept": "application/json, text/event-stream"})
        assert r.status_code == 200, r.text
        return _sse(r.text)["result"]

    def __call__(self, name, **args):
        res = self.raw(name, **args)
        assert not res.get("isError"), res
        if res.get("structuredContent"):
            return res["structuredContent"]
        return json.loads(res["content"][0]["text"])

    def fail(self, name, **args):
        res = self.raw(name, **args)
        assert res.get("isError"), res
        return json.loads(res["content"][0]["text"])


def make_agent(c, role="editor", mode="auto", name="claude"):
    r = c.post("/api/keys", json={"name": name, "role": role, "mode": mode})
    assert r.status_code == 200, r.text
    return Agent(c, r.json()["key"])


def project(c, title="Report"):
    r = c.post("/api/projects", json={"title": title})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def doc(c, pid, title, content="", folder=""):
    r = c.post(f"/api/projects/{pid}/docs", json={"title": title, "content": content, "folder": folder})
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture()
def solo(c):
    register_user(c, "alice")
    pid = project(c)
    return c, pid, make_agent(c)


def test_ls_paths_and_depth(solo):
    c, pid, a = solo
    doc(c, pid, "Intro", "= Intro")
    doc(c, pid, "Q1", "= Q1", folder="Berichte")
    root = a("ls")
    assert {"path": "/Report", "kind": "project", "role": "editor"} in root["entries"]
    top = {e["path"]: e["kind"] for e in a("ls", path="/Report")["entries"]}
    assert top["/Report/Intro"] == "doc" and top["/Report/Berichte"] == "folder" and top["/Report/.proposals"] == "proposals"
    deep = {e["path"] for e in a("ls", path="/Report", depth=0)["entries"]}
    assert "/Report/Berichte/Q1" in deep
    assert {e["path"] for e in a("ls", path="/Report/Berichte")["entries"]} == {"/Report/Berichte/Q1"}


def test_document_is_its_title_and_typ_suffix_is_accepted(solo):
    c, pid, a = solo
    doc(c, pid, "Intro", "line1\nline2\n")
    r = a("read", path="/Report/Intro.typ")
    assert r["path"] == "/Report/Intro" and r["content"] == "line1\nline2\n" and r["total_lines"] == 2
    assert a("read", path="/Report/intro", limit=1)["content"] == "line1"
    assert a.fail("read", path="/Report/Nope")["code"] == "not_found"


def test_write_creates_everything_and_needs_base_version_to_overwrite(solo):
    c, pid, a = solo
    assert a("write", path="/Brand New")["created"]
    assert a("write", path="/Brand New/Notes", content="hello")["created"]
    assert a("write", path="/Brand New/Berichte/", content="")["created"]
    assert a("write", path="/Report/Berichte/Q2", content="= Q2")["path"] == "/Report/Berichte/Q2"
    pic = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 64).decode()
    assert a("write", path="/Report/Berichte/Q2/img/logo.png", content_base64=pic)["created"]
    assert a("write", path="/Report/.library/style.typ", content="#let c = red")["created"]
    assert a("write", path="/.templates/memo.typ", content="= Memo")["created"]
    listing = {e["path"]: e["kind"] for e in a("ls", path="/Report", depth=0)["entries"]}
    assert listing["/Report/Berichte/Q2/img/logo.png"] == "file" and listing["/Report/.library/style.typ"] == "module"
    assert a("read", path="/.templates/memo.typ")["content"] == "= Memo"
    img = a.raw("read", path="/Report/Berichte/Q2/img/logo.png")
    assert any(x["type"] == "image" for x in img["content"])
    got = a("read", path="/Report/Berichte/Q2")
    stale = a.fail("write", path="/Report/Berichte/Q2", content="= Q2b")
    assert stale["code"] == "stale_version" and stale["version"] == got["version"]
    assert a("write", path="/Report/Berichte/Q2", content="= Q2b", base_version=got["version"])["version"]
    assert a("read", path="/Report/Berichte/Q2")["content"] == "= Q2b"
    assert a("write", path="/Report/Berichte/Q2", content="= forced", force=True)["version"]


def test_edit_atomic_errors_and_changed_since(solo):
    c, pid, a = solo
    doc(c, pid, "Plan", "alpha\nbeta\nalpha\ngamma\n")
    v = a("read", path="/Report/Plan")["version"]
    amb = a.fail("edit", path="/Report/Plan", edits=[{"old": "alpha", "new": "A"}])
    assert amb["code"] == "anchor_ambiguous" and [x["line"] for x in amb["candidates"]] == [1, 3]
    gone = a.fail("edit", path="/Report/Plan", edits=[{"old": "betta", "new": "B"}])
    assert gone["code"] == "anchor_gone" and gone["closest"]["line"] == 2
    ok = a("edit", path="/Report/Plan", base_version=v, edits=[{"old": "alpha", "new": "A", "all": True}, {"old": "gamma", "new": "G"}])
    assert ok["replaced"] == 3
    assert a("read", path="/Report/Plan")["content"] == "A\nbeta\nA\nG\n"
    again = a("edit", path="/Report/Plan", base_version=v, edits=[{"old": "beta", "new": "b"}])
    assert again["changed_since"] is True


def test_edit_keeps_concurrent_typing_in_the_live_room(solo):
    c, pid, a = solo
    did = doc(c, pid, "Live", "one\ntwo\nthree\n")
    room = sync.room(did)
    from pycrdt import Text
    text = room["doc"].get("typst", type=Text)
    with room["doc"].transaction():  # a person types at the end while the agent edits line 1
        text.insert(len(b"one\ntwo\nthree\n"), "typed by human\n")
    a("edit", path="/Report/Live", edits=[{"old": "one", "new": "ONE"}])
    assert str(room["doc"].get("typst", type=Text)) == "ONE\ntwo\nthree\ntyped by human\n"
    assert a("read", path="/Report/Live")["live"] is True
    sync.persist(did)
    con = __import__("backend.db", fromlist=["db"]).connect()
    try:
        assert con.execute("SELECT content FROM docs WHERE id=?", (did,)).fetchone()[0].startswith("ONE\n")
    finally:
        con.close()


def test_move_rename_references_and_trash_restore(solo):
    c, pid, a = solo
    doc(c, pid, "Main", '#include "part.typ"\n#image("pic.png")\n')
    a("write", path="/Report/Main/part.typ", content="part")
    a("write", path="/Report/.library/lib.typ", content="lib")
    moved = a("move", path="/Report/Main/part.typ", to="/Report/Main/sections/part2.typ")
    assert moved["updated_references"] == 1
    assert a("read", path="/Report/Main")["content"] == '#include "sections/part2.typ"\n#image("pic.png")\n'
    a("move", path="/Report/Main", to="/Report/Archiv/Final")
    assert a("read", path="/Report/Archiv/Final")["path"] == "/Report/Archiv/Final"
    assert a("read", path="/Report/Archiv/Final/sections/part2.typ")["content"] == "part"
    a("move", path="/Report/Archiv/", to="/Report/Old/")
    assert a("read", path="/Report/Old/Final")["path"] == "/Report/Old/Final"
    assert a.fail("move", path="/Report/Old/Final", to="/Elsewhere/X")["code"] == "not_found"
    a("delete", path="/Report/Old/Final")
    assert a.fail("read", path="/Report/Old/Final")["code"] == "not_found"
    trash = [e for e in a("ls", path="/.trash")["entries"] if e["name"] == "Final"]
    assert trash
    a("move", path=trash[0]["path"], to="/")
    assert a("read", path="/Report/Old/Final")["content"].startswith("#include")
    a("delete", path="/Report/.library/lib.typ")
    assert any(e["name"] == "lib.typ" for e in a("ls", path="/.trash")["entries"])
    assert a("move", path="/Report", to="/Renamed")["path"] == "/Renamed"


def test_copy_from_and_search(solo):
    c, pid, a = solo
    doc(c, pid, "Src", "needle in a haystack\nsecond\n")
    a("write", path="/Report/Src/data.csv", content="a,b\n1,needle\n")
    a("write", path="/Report/Copy", copy_from="/Report/Src")
    assert a("read", path="/Report/Copy")["content"].startswith("needle")
    hits = a("search", query="needle")["hits"]
    paths = {h["path"]: h for h in hits}
    assert paths["/Report/Src"]["line"] == 1 and "needle" in paths["/Report/Src"]["snippet"]
    assert paths["/Report/Src/data.csv"]["kind"] == "file" and paths["/Report/Src/data.csv"]["line"] == 2
    assert {h["path"] for h in a("search", query="needle", path="/Report/Src")["hits"]} == {"/Report/Src", "/Report/Src/data.csv"}
    assert a.fail("search", query="n")["code"] == "bad_request"


@pytest.mark.skipif(not shutil.which("typst"), reason="typst CLI missing")
def test_render_check_and_pages(solo):
    c, pid, a = solo
    doc(c, pid, "Good", "= Hi\n#lorem(30)\n")
    doc(c, pid, "Bad", "#let x = \n= oops #undefined\n")
    ok = a("render", path="/Report/Good")
    assert ok["ok"] and ok["pages"] == 1
    bad = a.fail("render", path="/Report/Bad")
    assert bad["code"] == "compile_error" and bad["diagnostics"][0]["file"] == "/Report/Bad" and bad["diagnostics"][0]["line"]
    shots = a.raw("render", path="/Report/Good", pages="1")
    assert any(x["type"] == "image" for x in shots["content"])


def test_export_and_upload_links(solo):
    c, pid, a = solo
    doc(c, pid, "Notes", "text\n")
    a("write", path="/Report/Notes/data.bin", content_base64=base64.b64encode(b"\x00\x01\x02").decode())
    exp = a("export", path="/Report/Notes/data.bin")
    assert base64.b64decode(exp["content_base64"]) == b"\x00\x01\x02"
    got = c.get(exp["url"].replace("http://testserver", ""))
    assert got.status_code == 200 and got.content == b"\x00\x01\x02"
    up = a("upload", path="/Report/Notes/big.bin")
    r = c.put(up["url"].replace("http://testserver", ""), content=b"x" * 1000)
    assert r.status_code == 200, r.text
    assert c.put(up["url"].replace("http://testserver", ""), content=b"y").status_code == 404  # one use
    assert {e["path"]: e for e in a("ls", path="/Report/Notes")["entries"]}["/Report/Notes/big.bin"]["size"] == 1000
    assert c.get("/api/transfer/nonsense").status_code == 404


def test_reviewer_key_cannot_write_directly_and_bearer_is_required(c):
    register_user(c, "alice")
    project(c)
    rev = make_agent(c, role="reviewer", name="rev")
    assert rev("write", path="/Report/Doc", content="x")["proposal"].startswith("sp_")  # a reviewer key proposes, never writes
    assert not [e for e in rev("ls", path="/Report")["entries"] if e["path"] == "/Report/Doc"]
    c.post("/api/logout")
    bad = Agent(c, "tpe_deadbeef_deadbeefdeadbeefdeadbeef")
    assert bad.fail("ls")["code"] == "unauthorized"
    login(c, "alice")


def test_text_file_and_document_convert_into_each_other(solo):
    c, pid, a = solo
    doc(c, pid, "Main", '#include "chapter.typ"\n')
    a("write", path="/Report/Main/chapter.typ", content="= Chapter\n")
    made = a("move", path="/Report/Main/chapter.typ", to="/Report/Kapitel/Chapter")
    assert made["converted"] == "file to document"
    assert a("read", path="/Report/Kapitel/Chapter")["content"] == "= Chapter\n"
    assert a.fail("read", path="/Report/Main/chapter.typ")["code"] == "not_found"
    back = a("move", path="/Report/Kapitel/Chapter", to="/Report/Main/chapter.typ")
    assert back["converted"] == "document to file"
    assert a("read", path="/Report/Main/chapter.typ")["content"] == "= Chapter\n"
    assert a.fail("read", path="/Report/Kapitel/Chapter")["code"] == "not_found"


def test_typ_files_convert_to_documents_and_modules_and_warn_about_includes(solo):
    c, pid, a = solo
    doc(c, pid, "Main", '#include "chapter.typ"\n')
    a("write", path="/Report/Main/chapter.typ", content="= Chapter\n")
    a("write", path="/Report/Main/data.csv", content="a,b\n")
    assert "converted" not in a.fail("move", path="/Report/Main/data.csv", to="/Report/Data")  # only .typ files convert
    to_module = a("move", path="/Report/Main/chapter.typ", to="/Report/.library/chapter.typ")
    assert to_module["converted"] == "file to module" and "broken_references" not in to_module  # still reachable as a module
    assert a("read", path="/Report/.library/chapter.typ")["content"] == "= Chapter\n"
    assert a.fail("read", path="/Report/Main/chapter.typ")["code"] == "not_found"
    to_doc = a("move", path="/Report/.library/chapter.typ", to="/Report/Kapitel/Chapter")
    assert to_doc["converted"] == "module to document"
    assert to_doc["broken_references"] == ["/Report/Main"]  # Main still includes it
    assert a("read", path="/Report/Kapitel/Chapter")["content"] == "= Chapter\n"
    c_rest = c.post(f"/api/projects/{pid}/convert", json={"name": "x.typ", "to": "module"})
    assert c_rest.status_code == 400


def test_document_converts_to_a_module(solo):
    c, pid, a = solo
    doc(c, pid, "Layout", "#let accent = red\n")
    done = a("move", path="/Report/Layout", to="/Report/.library/Layout.typ")
    assert done["converted"] == "document to module"
    assert a("read", path="/Report/.library/Layout.typ")["content"] == "#let accent = red\n"
    assert a.fail("read", path="/Report/Layout")["code"] == "not_found"
    rest = c.post(f"/api/projects/{pid}/convert", json={"doc_id": "d_nope", "document": True, "to": "document"})
    assert rest.status_code == 400


def test_conversions_keep_the_folder(solo):
    c, pid, a = solo
    did = doc(c, pid, "Layout", "#let x = 1\n", folder="Archiv")
    r = c.post(f"/api/projects/{pid}/convert", json={"doc_id": did, "document": True, "to": "module"})
    assert r.status_code == 200 and r.json()["name"] == "Archiv/Layout.typ"
    paths = {e["path"] for e in a("ls", path="/Report", depth=0)["entries"]}
    assert "/Report/.library/Archiv/Layout.typ" in paths and "/Report/Archiv" in paths  # the emptied folder survives
    r = c.post(f"/api/projects/{pid}/convert", json={"name": "Archiv/Layout.typ", "to": "document"})
    assert r.status_code == 200
    assert a("read", path="/Report/Archiv/Layout")["content"] == "#let x = 1\n"
    main = doc(c, pid, "Main", "= Main\n", folder="Kapitel")
    a("write", path="/Report/Kapitel/Main/part.typ", content="= Part\n")
    r = c.post(f"/api/projects/{pid}/convert", json={"doc_id": main, "name": "part.typ", "to": "document"})
    assert r.status_code == 200
    assert a("read", path="/Report/Kapitel/part")["content"] == "= Part\n"  # lands next to its document


def test_paths_are_returned_as_stored_and_junk_is_refused(solo):
    c, pid, a = solo
    made = a("write", path="/Report/Über uns/Größe", content="x")
    assert a("read", path=made["path"])["content"] == "x"  # the echoed path is the one that works
    a("write", path="/Report/Doc", content="d")
    pic = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    assert a.fail("write", path="/Report/Typo/a.png", content_base64=pic)["code"] == "not_found"  # no junk document
    assert a("write", path="/Report/Doc/ü bild.png", content_base64=pic)["path"].endswith("/_ bild.png")
    assert a.fail("delete", path="/Report/Nowhere/")["code"] == "not_found"
    assert a.fail("read", path="/Report/Doc", limit=-1)["code"] == "bad_request"
    assert a.fail("write", path="/Report/Doc", content="y")["message"].startswith("base_version is missing")


def test_comment_validates_anchors_and_search_finds_modules(solo):
    c, pid, a = solo
    doc(c, pid, "Notes", "alpha\nbeta\n")
    assert a.fail("comment", path="/Report/Notes", text="x", quote="nope")["code"] == "bad_request"
    assert a.fail("comment", path="/Report/Notes", text="x", line=99)["code"] == "bad_request"
    cid = a("comment", path="/Report/Notes", text="ok", line=2)["id"]
    assert a.fail("comment", path="/Report/Notes", text="edit?", id=cid)["code"] == "bad_request"
    a("write", path="/Report/.library/helper.typ", content="#let h = 1")
    assert {"path": "/Report/.library/helper.typ", "kind": "module", "count": 0, "line": 0, "snippet": ""} in a("search", query="helper")["hits"]
    assert a.fail("search", query="helper", kind="bogus")["code"] == "bad_request"
    assert a.fail("search", query="helper", path="/Nope")["code"] == "not_found"


def test_conversions_honour_names_and_refuse_attachment_loss(solo):
    c, pid, a = solo
    doc(c, pid, "Main", "= M\n")
    a("write", path="/Report/Main/part.typ", content="p")
    assert a("move", path="/Report/Main/part.typ", to="/Report/.library/renamed.typ")["converted"] == "file to module"
    assert a("read", path="/Report/.library/renamed.typ")["content"] == "p"
    doc(c, pid, "Solo", "s")
    a("write", path="/Report/Solo/pic.txt", content="t")
    assert a.fail("move", path="/Report/Solo", to="/Report/.library/sub/Solo.typ")["code"] == "conflict"  # attachments would be left behind
    a("delete", path="/Report/Solo/pic.txt")
    assert a("move", path="/Report/Solo", to="/Report/.library/sub/Teil.typ")["converted"] == "document to module"
    assert a("read", path="/Report/.library/sub/Teil.typ")["content"] == "s"
