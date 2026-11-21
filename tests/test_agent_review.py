"""Agent proposals, comments and inbox: packages the server assembles and humans accept hunk by hunk."""
import pytest
from conftest import login, register_user
from test_agent import doc, make_agent, project

from backend import db
from backend.mcp_review import hunks
from backend.services.change_packages import apply_changes


def test_hunks_are_unique_non_overlapping_and_rebuild_the_text():
    base = "a\nb\nsame\nsame\nsame\nz\n"
    new = "A\nb\nsame\nSAME\nsame\nz\nextra\n"
    parts = hunks(base, new)
    assert len(parts) >= 2
    for h in parts:
        assert base.count(h["old_string"]) == 1
    assert apply_changes(base, parts) == new
    assert hunks("", "fresh\n") == [{"old_string": "", "new_string": "fresh\n"}]
    assert hunks("same\n", "same\n") == []


def members(c, pid, name, role="editor"):
    register_user(c, name)
    login(c, "alice")
    assert c.post(f"/api/projects/{pid}/members", json={"username": name, "role": role}).status_code == 200


@pytest.fixture()
def shared(c):
    register_user(c, "alice")
    pid = project(c)
    members(c, pid, "bob")
    login(c, "alice")
    return c, pid


def package(c, pid, pkg_id):
    r = c.get(f"/api/projects/{pid}/proposals/{pkg_id}")
    assert r.status_code == 200, r.text
    return r.json()


def test_shared_project_edits_become_one_package_with_hunks_folders_and_moves(shared):
    c, pid = shared
    a = make_agent(c)
    doc(c, pid, "Intro", "one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n")
    doc(c, pid, "Old", "old text\n")
    doc(c, pid, "Gone", "bye\n")
    first = a("edit", path="/Report/Intro", edits=[{"old": "one", "new": "ONE"}])
    pkg_id = first["proposal"]
    second = a("edit", path="/Report/Intro", edits=[{"old": "ten", "new": "TEN"}], package=pkg_id)
    assert second["proposal"] == pkg_id and second["revision"] == first["revision"] + 1
    a("write", path="/Report/Kapitel/New", content="= New", package=pkg_id)
    a("move", path="/Report/Old", to="/Report/Archiv/Old", package=pkg_id)
    a("delete", path="/Report/Gone", package=pkg_id)
    got = a("read", path=f"/Report/.proposals/{pkg_id}")
    by_path = {f["path"]: f for f in got["files"]}
    assert len(by_path["/Report/Intro"]["changes"]) == 2  # ONE and TEN stay separate hunks
    assert by_path["/Report/Kapitel/New"]["action"] == "add" and by_path["/Report/Archiv/Old"]["action"] == "rename"
    assert by_path["/Report/Gone"]["action"] == "delete"
    # nothing changed yet
    assert a("read", path="/Report/Intro")["content"].startswith("one\n")
    listed = a("ls", path="/Report/.proposals")["entries"]
    assert listed[0]["files"] == 4 and listed[0]["changes"] >= 5
    # a human accepts ONE hunk of the file, then the rest of the package
    pk = package(c, pid, pkg_id)
    intro = next(f for f in pk["files"] if f["kind"] == "document" and f["action"] == "modify")
    assert c.post(f"/api/projects/{pid}/proposals/{pkg_id}/accept",
                  json={"revision": pk["revision"], "file_id": intro["id"], "change_id": intro["changes"][0]["id"]}).status_code == 200
    mid = a("read", path="/Report/Intro")["content"]
    assert mid.startswith("ONE\n") and mid.endswith("ten\n")
    pk = package(c, pid, pkg_id)
    assert c.post(f"/api/projects/{pid}/proposals/{pkg_id}/accept", json={"revision": pk["revision"]}).status_code == 200
    assert a("read", path="/Report/Intro")["content"].endswith("TEN\n")
    assert a("read", path="/Report/Kapitel/New")["content"] == "= New"
    assert a("read", path="/Report/Archiv/Old")["content"] == "old text\n"
    assert a.fail("read", path="/Report/Gone")["code"] == "not_found"


def test_agent_deletes_its_own_proposal_and_owner_verdicts_reach_the_authors_inbox(shared):
    c, pid = shared
    login(c, "bob")
    b = make_agent(c, name="bobbot")
    doc_id = None
    login(c, "alice")
    doc_id = doc(c, pid, "Plan", "x\ny\n")
    assert doc_id
    login(c, "bob")
    sent = b("edit", path="/Report@alice/Plan", edits=[{"old": "x", "new": "X"}])
    pkg = sent["proposal"]
    assert b("ls", path="/Report@alice/.proposals")["entries"][0]["by"] == "bobbot"
    b("delete", path=f"/Report@alice/.proposals/{pkg}")
    assert b("ls", path="/Report@alice/.proposals")["entries"] == []
    again = b("edit", path="/Report@alice/Plan", edits=[{"old": "y", "new": "Y"}])["proposal"]
    login(c, "alice")
    pk = package(c, pid, again)
    assert c.post(f"/api/projects/{pid}/proposals/{again}/accept", json={"revision": pk["revision"]}).status_code == 200
    login(c, "bob")
    items = b("inbox")["items"]
    assert items and items[0]["type"] == "reviewed" and "accepted" in items[0]["text"]
    b("inbox", ack=[items[0]["id"]])
    assert b("inbox")["items"] == []


def test_key_modes_decide_between_direct_and_proposal(shared):
    c, pid = shared
    doc(c, pid, "Doc", "text\n")
    direct = make_agent(c, mode="direct", name="direct")
    direct("edit", path="/Report/Doc", edits=[{"old": "text", "new": "TEXT"}])  # direct although the project is shared
    assert direct("read", path="/Report/Doc")["content"] == "TEXT\n"
    solo = project(c, "Alone")
    doc(c, solo, "Solo", "text\n")
    propose = make_agent(c, mode="propose", name="careful")
    assert propose("edit", path="/Alone/Solo", edits=[{"old": "text", "new": "T"}])["proposal"]
    assert propose("read", path="/Alone/Solo")["content"] == "text\n"
    auto = make_agent(c, name="auto")
    auto("edit", path="/Alone/Solo", edits=[{"old": "text", "new": "T"}])  # solo project: direct
    assert auto("read", path="/Alone/Solo")["content"] == "T\n"


def test_propose_tool_packs_ops_and_corrects_the_package(shared):
    c, pid = shared
    doc(c, pid, "Main", '#include "part.typ"\n')
    a = make_agent(c)
    a("write", path="/Report/Main/part.typ", content="part", package="")
    pkg = [e for e in a("ls", path="/Report/.proposals")["entries"]][0]["path"].rsplit("/", 1)[-1]
    a("delete", path=f"/Report/.proposals/{pkg}")
    r = a("propose", project="/Report", title="Restructure", ops=[
        {"op": "edit", "path": "/Report/Main", "edits": [{"old": "part", "new": "section"}]},
        {"op": "write", "path": "/Report/Main/section.typ", "content": "sec"}])
    assert r["title"] == "Restructure" and r["files"] == 2
    assert a.fail("propose", project="/Report/Main", ops=[])["code"] == "bad_path"
    same = a.fail("propose", project="/Report", ops=[{"op": "edit", "path": "/Report/Main", "edits": [{"old": "include", "new": "include"}]}])
    assert same["code"] == "bad_request"


def test_comments_quote_anchor_resolve_delete_and_key_mentions(shared):
    c, pid = shared
    did = doc(c, pid, "Notes", "alpha\nbeta\ngamma\n")
    assert did
    a = make_agent(c, name="claude")
    made = a("comment", path="/Report/Notes", text="check this", quote="gamma")
    assert made["line"] == 3
    read = a("read", path="/Report/Notes")
    assert read["comments"][0]["line"] == 3 and read["comments"][0]["text"] == "check this" and read["comments"][0]["quote"] == "gamma"
    a("comment", path="/Report/Notes", text="done?", reply_to=made["id"])
    assert len(a("read", path="/Report/Notes")["comments"][0]["replies"]) == 1
    a("comment", path="/Report/Notes", id=made["id"], resolved=True)
    assert a("read", path="/Report/Notes")["comments"] == []
    other = a("comment", path="/Report/Notes", text="stale idea", line=1)
    a("comment", path="/Report/Notes", id=other["id"], delete=True)
    assert a("read", path="/Report/Notes")["comments"] == []
    # a human calls the agent with @claude: the item shows up for the key owner
    r = c.post(f"/api/docs/{did}/comments", json={"text": "@claude please tighten this", "anchor": 2})
    assert r.status_code == 200
    r = c.post(f"/api/docs/{did}/comments", json={"text": "@someone else", "anchor": 2})
    items = a("inbox")["items"]
    assert [i["text"] for i in items] == ["@claude please tighten this"] and items[0]["path"] == "/Report/Notes"
    assert a("inbox", since=a("inbox")["since"])["items"] == []


def test_reviewer_key_proposes_but_never_reaches_unshared_projects(c):
    register_user(c, "alice")
    pid = project(c)
    doc(c, pid, "Doc", "text\n")
    register_user(c, "mallory")
    rev = make_agent(c, role="reviewer", name="rev")
    assert rev.fail("read", path="/Report@alice/Doc")["code"] == "not_found"
    login(c, "alice")
    r = make_agent(c, role="reviewer", name="rev2")
    assert r("edit", path="/Report/Doc", edits=[{"old": "text", "new": "T"}])["proposal"]
    assert r("read", path="/Report/Doc")["content"] == "text\n"
    con = db.connect()
    try:
        assert con.execute("SELECT COUNT(*) FROM agent_log WHERE ok=1").fetchone()[0] >= 2
    finally:
        con.close()


def test_converting_between_document_and_file_is_a_proposal_in_shared_projects(shared):
    c, pid = shared
    doc(c, pid, "Main", "= Main\n")
    a = make_agent(c, mode="direct", name="setup")
    a("write", path="/Report/Main/chapter.typ", content="= Chapter\n")
    p = make_agent(c, mode="propose", name="careful")
    sent = p("move", path="/Report/Main/chapter.typ", to="/Report/Kapitel/Chapter")
    assert sent["proposal"] and sent["files"] == 2
    assert a("read", path="/Report/Main/chapter.typ")["content"] == "= Chapter\n"  # nothing changed yet
    pk = package(c, pid, sent["proposal"])
    r = c.post(f"/api/projects/{pid}/proposals/{sent['proposal']}/accept", json={"revision": pk["revision"]})
    assert r.status_code == 200, r.text
    assert a("read", path="/Report/Kapitel/Chapter")["content"] == "= Chapter\n"
    assert a.fail("read", path="/Report/Main/chapter.typ")["code"] == "not_found"
    back = p("move", path="/Report/Kapitel/Chapter", to="/Report/Main/chapter.typ")
    pk = package(c, pid, back["proposal"])
    assert c.post(f"/api/projects/{pid}/proposals/{back['proposal']}/accept", json={"revision": pk["revision"]}).status_code == 200
    assert a("read", path="/Report/Main/chapter.typ")["content"] == "= Chapter\n"
    assert a.fail("read", path="/Report/Kapitel/Chapter")["code"] == "not_found"
