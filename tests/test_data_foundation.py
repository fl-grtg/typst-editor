"""Wave 1D Daten-Fundament: files table, quota/search from table, events,
read-mode, notifications, migration backups, FileStore."""
import sqlite3

import pytest
from conftest import login, make_doc, register_user

from backend import auth, db, deps
from backend.routers.events import match_event, split_event
from backend.services import notifications as notif_svc
from backend.services import quota as quota_svc
from backend.services import sidebar as sidebar_svc
from backend.services.docfiles import LocalFileStore, safe_name, sync_doc_files


def _watch(user):
    import asyncio

    entry = (asyncio.get_running_loop(), asyncio.Queue())
    sidebar_svc._SIDEBAR_Q.setdefault(user, set()).add(entry)
    return entry


def _unwatch(user, entry):
    sidebar_svc._SIDEBAR_Q.get(user, set()).discard(entry)


def _old_db(tmp_path, monkeypatch):
    """Realistic old-schema DB: fresh init, then downgraded to v12 state."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "old.db")
    monkeypatch.setattr(deps, "FILES_DIR", tmp_path / "files")
    db.init_db()
    con = db.connect()
    try:
        con.execute("DROP TABLE files")
        con.execute("DROP TABLE notifications")
        con.execute("DROP TABLE read_tokens")
        con.execute("DELETE FROM schema_version WHERE v >= 13")
        con.execute("INSERT INTO users (name, hash) VALUES (?,?)", ("alice", "x"))
        con.execute("INSERT INTO docs (id, owner, title, content, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?)", ("d_x", "alice", "Alt", "inhalt", "t", "t"))
        con.commit()
    finally:
        con.close()
    fdir = tmp_path / "files" / "d_x"
    fdir.mkdir(parents=True)
    (fdir / "a.png").write_bytes(b"1234567890")
    (fdir / "sub").mkdir()
    (fdir / "sub" / "b.typ").write_text("hi")
    (fdir / "a.png.tmp.ab12").write_bytes(b"junk")  # in-flight buffer: skipped
    orph = tmp_path / "files" / "d_orphan"
    orph.mkdir(parents=True)
    (orph / "x.png").write_bytes(b"orphan")  # no doc row: skipped
    return tmp_path / "old.db"


def test_migrate_v13_backfills_files_table(tmp_path, monkeypatch):
    dbpath = _old_db(tmp_path, monkeypatch)
    con = db.connect()
    try:
        assert con.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"] == 12
        con.execute("SELECT 1 FROM files").fetchone()
        raise AssertionError("files should not exist yet")
    except sqlite3.OperationalError:
        pass  # expected: old schema
    finally:
        con.close()
    con = db.connect()
    try:
        db.migrate(con)
        con.commit()
        rows = con.execute("SELECT path, size FROM files ORDER BY path").fetchall()
        assert [(r["path"], r["size"]) for r in rows] == [("a.png", 10), ("sub/b.typ", 2)]
        assert con.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"] == 13
        assert con.execute("SELECT COUNT(*) AS n FROM notifications").fetchone()["n"] == 0
    finally:
        con.close()
    assert dbpath.is_file()
    # Re-run: idempotent, no duplicate rows, no second backup.
    con = db.connect()
    try:
        db.migrate(con)
        con.commit()
        assert con.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"] == 2
    finally:
        con.close()


def test_migrate_backup_written(tmp_path, monkeypatch):
    _old_db(tmp_path, monkeypatch)
    con = db.connect()
    try:
        db.migrate(con)
        con.commit()
    finally:
        con.close()
    backs = list(tmp_path.glob("old-migrate-*.db"))
    assert len(backs) == 1
    bcon = sqlite3.connect(str(backs[0]))
    try:
        assert bcon.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert bcon.execute("SELECT COUNT(*) FROM docs WHERE id='d_x'").fetchone()[0] == 1
        tables = {r[0] for r in bcon.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "files" not in tables  # pre-migration snapshot, not the migrated state
    finally:
        bcon.close()


def test_fresh_init_writes_no_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "fresh.db")
    monkeypatch.setattr(deps, "FILES_DIR", tmp_path / "files")
    db.init_db()
    assert list(tmp_path.glob("fresh-migrate-*.db")) == []


def test_quota_reads_table_not_disk(c):
    from backend import deps as _deps

    register_user(c, "alice")
    did = make_doc(c, "Q")
    base = quota_svc.user_bytes("alice")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("a.png", b"x" * 100)}).status_code == 200
    assert quota_svc.user_bytes("alice") == base + 100
    # Bypass: raw disk write is invisible until the next listing (contract).
    (_deps.get_files_dir() / did / "sneaky.png").write_bytes(b"y" * 50)
    assert quota_svc.user_bytes("alice") == base + 100
    assert c.get(f"/api/docs/{did}/files").status_code == 200
    assert quota_svc.user_bytes("alice") == base + 150
    assert c.delete(f"/api/docs/{did}/files/sneaky.png").status_code == 200
    assert quota_svc.user_bytes("alice") == base + 100


def test_hard_delete_drops_file_rows(c):
    register_user(c, "alice")
    did = make_doc(c, "Weg")
    pre = quota_svc.user_bytes("alice")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("a.png", b"x" * 40)}).status_code == 200
    assert quota_svc.user_bytes("alice") == pre + 40
    assert c.delete(f"/api/docs/{did}").status_code == 200  # trash
    assert c.delete(f"/api/docs/{did}").status_code == 200  # hard delete
    con = db.connect()
    try:
        assert con.execute("SELECT COUNT(*) AS n FROM files WHERE doc_id=?", (did,)).fetchone()["n"] == 0
    finally:
        con.close()
    # File rows (40) and the doc content ("hi") are gone via FK cascade.
    assert quota_svc.user_bytes("alice") == pre - 2


def test_search_reads_table_not_disk(c):
    from backend import deps as _deps

    register_user(c, "alice")
    did = make_doc(c, "Suche", content="ganz normaler Inhalt")
    assert c.post(f"/api/docs/{did}/files",
                  files={"f": ("refs.bib", b"@article{Mueller2024quantenphysik, author={M}}")}).status_code == 200
    hits = c.get("/api/search", params={"q": "mueller2024quanten"}).json()["hits"]
    assert [h["id"] for h in hits] == [did]
    # Bypass write: invisible until the next listing (contract).
    (_deps.get_files_dir() / did / "zqxwjk-notizen.csv").write_text("a,b\n")
    assert c.get("/api/search", params={"q": "zqxwjk"}).json()["hits"] == []
    c.get(f"/api/docs/{did}/files")
    hits = c.get("/api/search", params={"q": "zqxwjk"}).json()["hits"]
    assert [h["id"] for h in hits] == [did]
    # API delete removes the hit again.
    assert c.delete(f"/api/docs/{did}/files/refs.bib").status_code == 200
    assert c.get("/api/search", params={"q": "mueller2024quanten"}).json()["hits"] == []


def test_subpath_upload(c):
    register_user(c, "alice")
    did = make_doc(c, "Pfade")
    r = c.post(f"/api/docs/{did}/files", files={"f": ("sub/a.png", b"12345")})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "sub/a.png"
    names = [f["name"] for f in c.get(f"/api/docs/{did}/files").json()["files"]]
    assert "sub/a.png" in names
    assert c.get(f"/api/docs/{did}/files/sub/a.png").status_code == 200
    assert c.post(f"/api/docs/{did}/files/sub/n.typ/text", json={"content": "hi"}).status_code == 200
    assert c.get(f"/api/docs/{did}/files/sub/n.typ/text").json()["content"] == "hi"
    assert quota_svc.user_bytes("alice") >= 7  # 5 + 2 bytes counted from the table


def test_safe_name_paths():
    from fastapi import HTTPException

    assert safe_name("a.png") == "a.png"
    assert safe_name("sub/dir/b.typ") == "sub/dir/b.typ"
    with pytest.raises(HTTPException):
        safe_name("../evil.png")
    with pytest.raises(HTTPException):
        safe_name("tool.exe")
    with pytest.raises(HTTPException):
        safe_name("a.png.tmp.123")


def test_local_filestore(tmp_path):
    from fastapi import HTTPException

    st = LocalFileStore(tmp_path)
    assert st.put("d_1", "sub/a.txt", b"hello") == 5
    assert st.get("d_1", "sub/a.txt") == b"hello"
    assert [e.path for e in st.list("d_1")] == ["sub/a.txt"]
    assert st.stat("d_1", "sub/a.txt").size == 5
    assert st.delete("d_1", "sub/a.txt") is True
    assert st.delete("d_1", "sub/a.txt") is False
    assert st.list("d_1") == []
    with pytest.raises(HTTPException):
        st.doc_path("d_1", "../escape.txt")


def test_sync_doc_files_heals(c):
    from backend import deps as _deps

    register_user(c, "alice")
    did = make_doc(c, "Heal")
    (_deps.get_files_dir() / did).mkdir(parents=True, exist_ok=True)
    (_deps.get_files_dir() / did / "ext.png").write_bytes(b"1234")
    assert sync_doc_files(did) == 1
    assert quota_svc.user_bytes("alice") >= 4


def test_read_token_flow(c):
    register_user(c, "alice")
    did = make_doc(c, "Lesemodus", content="geheimer Inhalt")
    r = c.post(f"/api/docs/{did}/read-token", json={})
    assert r.status_code == 200, r.text
    token, hint = r.json()["token"], r.json()["hint"]
    c.post("/api/logout")
    pub = c.get(f"/api/r/{token}")
    assert pub.status_code == 200, pub.text
    assert pub.json()["content"] == "geheimer Inhalt"
    assert pub.json()["title"] == "Lesemodus"
    assert c.get("/api/r/ungültig").status_code == 404
    # Reviewer cannot mint tokens.
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/read-token", json={}).status_code == 403
    # Owner revokes: link dies immediately.
    login(c, "alice")
    toks = c.get(f"/api/docs/{did}/read-tokens").json()["tokens"]
    assert [t["hint"] for t in toks] == [hint]
    assert c.delete(f"/api/docs/{did}/read-tokens/{hint}").status_code == 200
    c.post("/api/logout")
    assert c.get(f"/api/r/{token}").status_code == 404


def test_read_token_trash_and_expiry(c):
    register_user(c, "alice")
    did = make_doc(c, "Vergänglich", content="x")
    tok = c.post(f"/api/docs/{did}/read-token", json={"expires_in_days": 7}).json()["token"]
    c.post("/api/logout")
    assert c.get(f"/api/r/{tok}").status_code == 200
    # Expired token is purged on read.
    con = db.connect()
    try:
        con.execute("UPDATE read_tokens SET expires_at='2000-01-01T00:00:00+00:00' "
                    "WHERE token_hash=?", (auth.sha(tok),))
        con.commit()
    finally:
        con.close()
    assert c.get(f"/api/r/{tok}").status_code == 404
    # Trashed doc reads 404, like an invalid link (no validity oracle).
    login(c, "alice")
    tok2 = c.post(f"/api/docs/{did}/read-token", json={}).json()["token"]
    assert c.delete(f"/api/docs/{did}").status_code == 200
    c.post("/api/logout")
    assert c.get(f"/api/r/{tok2}").status_code == 404


def test_read_token_rate_limit(c, monkeypatch):
    from types import SimpleNamespace

    from backend import config as backend_config

    register_user(c, "alice")
    did = make_doc(c, "Limit", content="x")
    tok = c.post(f"/api/docs/{did}/read-token", json={}).json()["token"]
    c.post("/api/logout")
    real = backend_config.load()
    monkeypatch.setattr(backend_config, "load",
                        lambda: SimpleNamespace(**{**vars(real), "RATE_READ_PER_MIN": 3}))
    for _ in range(3):
        assert c.get(f"/api/r/{tok}").status_code == 200
    assert c.get(f"/api/r/{tok}").status_code == 429


def test_notification_write_path(c):
    register_user(c, "alice")
    nid = notif_svc.create_notification("alice", "comment", "d_9", "Antwort da")
    assert notif_svc.unread_count("alice") == 1
    assert notif_svc.mark_read(nid, "alice") is True
    assert notif_svc.unread_count("alice") == 0
    assert notif_svc.mark_read(nid, "bob") is False
    con = db.connect()
    try:
        r = con.execute("SELECT recipient, type, doc_id, text, is_read FROM notifications WHERE id=?",
                        (nid,)).fetchone()
        assert (r["recipient"], r["type"], r["doc_id"], r["text"], r["is_read"]) == (
            "alice", "comment", "d_9", "Antwort da", 1)
    finally:
        con.close()


@pytest.mark.anyio
async def test_notification_event(c):
    import asyncio

    register_user(c, "alice")
    entry = _watch("alice")
    try:
        notif_svc.create_notification("alice", "comment", "d_9", "Antwort da")
        assert await asyncio.wait_for(entry[1].get(), timeout=5) == "notification:d_9"
    finally:
        _unwatch("alice", entry)


def test_split_and_match_event():
    assert split_event("sidebar") == ("sidebar", "")
    assert split_event("file:d_1") == ("file", "d_1")
    assert match_event("file:d_1", "") is True
    assert match_event("sidebar", "") is True
    assert match_event("file:d_1", "d_1") is True
    assert match_event("file:d_2", "d_1") is False
    assert match_event("sidebar", "d_1") is False
    assert match_event("notification:d_1", "d_1") is True


@pytest.mark.anyio
async def test_file_event_on_upload_and_sharee(c):
    import asyncio

    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Ereignis")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"})
    ea, eb = _watch("alice"), _watch("bob")
    try:
        assert c.post(f"/api/docs/{did}/files", files={"f": ("a.png", b"1")}).status_code == 200
        assert await asyncio.wait_for(ea[1].get(), timeout=5) == f"file:{did}"
        assert await asyncio.wait_for(eb[1].get(), timeout=5) == f"file:{did}"
        assert c.delete(f"/api/docs/{did}/files/a.png").status_code == 200
        assert await asyncio.wait_for(ea[1].get(), timeout=5) == f"file:{did}"
    finally:
        _unwatch("alice", ea)
        _unwatch("bob", eb)


@pytest.mark.anyio
async def test_emit_helpers(c):
    import asyncio

    register_user(c, "alice")
    entry = _watch("alice")
    try:
        sidebar_svc.emit("alice", "comment", "d_7")
        assert await asyncio.wait_for(entry[1].get(), timeout=5) == "comment:d_7"
        sidebar_svc.emit("alice", "bogus", "d_7")  # dropped fail-closed
        await asyncio.sleep(0.2)
        assert entry[1].empty()
    finally:
        _unwatch("alice", entry)


def test_events_doc_filter_guards_access(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Privat")
    login(c, "bob")
    assert c.get("/api/events", params={"doc_id": did}).status_code == 404
    assert c.get("/api/events", params={"doc_id": "nope"}).status_code == 404


def test_mcp_text_write_updates_table_and_quota(c):
    """R1 blocker 1: MCP file writes hit the files table immediately."""
    from backend import mcp_tools as mcp

    register_user(c, "alice")
    make_doc(c, "MCPDatei")
    base = quota_svc.user_bytes("alice")
    mcp.op_create("alice", "owner", "/docs/MCPDatei/notizen.typ", "eins zwei drei")
    con = db.connect()
    try:
        row = con.execute("SELECT size FROM files WHERE path=? AND doc_id IN "
                          "(SELECT id FROM docs WHERE owner=? AND title=?)",
                          ("notizen.typ", "alice", "MCPDatei")).fetchone()
    finally:
        con.close()
    assert row is not None  # write-through, no list_files healing needed
    assert row["size"] == len(b"eins zwei drei")
    assert quota_svc.user_bytes("alice") == base + row["size"]


def test_duplicate_copies_files_table_rows(c):
    """R1 blocker 1: duplicated docs carry their files-table rows."""
    register_user(c, "alice")
    did = make_doc(c, "Vorlage")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("bild.png", b"x" * 30)}).status_code == 200
    assert c.post(f"/api/docs/{did}/files/data.typ/text", json={"content": "hallo"}).status_code == 200
    nid = c.post(f"/api/docs/{did}/duplicate").json()["id"]
    con = db.connect()
    try:
        src = con.execute("SELECT path, size FROM files WHERE doc_id=? ORDER BY path", (did,)).fetchall()
        dst = con.execute("SELECT path, size FROM files WHERE doc_id=? ORDER BY path", (nid,)).fetchall()
    finally:
        con.close()
    assert [(r["path"], r["size"]) for r in dst] == [(r["path"], r["size"]) for r in src] != []
    listed = {f["name"]: f["size"] for f in c.get(f"/api/docs/{nid}/files").json()["files"]}
    assert listed == {r["path"]: r["size"] for r in src}


def test_search_finds_duplicated_filename(c):
    """R1 blocker 1: search reads the copied rows (filename hit on the copy)."""
    register_user(c, "alice")
    did = make_doc(c, "Original", content="ganz normaler Inhalt")
    name = "zqxwjk-protokoll.csv"
    assert c.post(f"/api/docs/{did}/files", files={"f": (name, b"a,b\n1,2\n")}).status_code == 200
    nid = c.post(f"/api/docs/{did}/duplicate").json()["id"]
    hits = c.get("/api/search", params={"q": "zqxwjk-protokoll"}).json()["hits"]
    assert {h["id"] for h in hits} == {did, nid}
