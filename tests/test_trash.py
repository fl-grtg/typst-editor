from conftest import login, make_doc, register_user

from backend import db
from backend import main as backend_main
from backend.services import quota


def test_file_listing_cannot_reconcile_an_uncommitted_restore(c, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from backend.services.docfiles import store

    register_user(c, "alice")
    did = make_doc(c, "Restore race")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("race.txt", b"restored")}).status_code == 200
    assert c.delete(f"/api/docs/{did}/files/race.txt").status_code == 200
    entry = _trash_for(c, "race.txt")[0]
    published, resume, reading = threading.Event(), threading.Event(), threading.Event()
    put = store.put

    def publish(*args):
        put(*args)
        published.set()
        assert resume.wait(10)

    def read():
        reading.set()
        return c.get(f"/api/docs/{did}/files")

    monkeypatch.setattr(store, "put", publish)
    with ThreadPoolExecutor(2) as pool:
        restore = pool.submit(c.post, f"/api/trash/{entry['id']}/restore")
        try:
            assert published.wait(10)
            listing = pool.submit(read)
            assert reading.wait(10)
            # The reader waits on the upload lock until metadata is committed.
            assert not listing.done()
        finally:
            resume.set()
        response = restore.result(timeout=10)
        assert response.status_code == 200, response.text
        assert listing.result(timeout=10).json()["files"][0]["name"] == "race.txt"


def _trash_for(c, title):
    return [t for t in c.get("/api/docs").json()["trash"] if t["title"] == title and t.get("doc_id")]


def test_delete_twice_gone(c):
    register_user(c, "alice")
    did = make_doc(c, "Papierkorb")
    assert c.delete(f"/api/docs/{did}").json()["trashed"] is True
    assert c.delete(f"/api/docs/{did}").json()["trashed"] is False
    assert c.get(f"/api/docs/{did}").status_code == 404


def test_trashed_410(c):
    register_user(c, "alice")
    did = make_doc(c, "Papierkorb2")
    c.delete(f"/api/docs/{did}")
    assert c.get(f"/api/docs/{did}").status_code == 410
    assert c.post(f"/api/docs/{did}/save", json={"content": "x"}).status_code == 410


def test_restore(c):
    register_user(c, "alice")
    did = make_doc(c, "Papierkorb3")
    c.delete(f"/api/docs/{did}")
    assert c.post(f"/api/docs/{did}/restore").status_code == 200
    assert c.get(f"/api/docs/{did}").status_code == 200


def test_foreign_restore_403_404(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Papierkorb4")
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/restore").status_code == 404  # need_access hides existence


def test_reap_trash_dirs(c):
    register_user(c, "alice")
    keep = make_doc(c, "ReapKeep")
    gone = make_doc(c, "ReapGone")
    both = make_doc(c, "ReapBoth")
    fdir = backend_main.get_files_dir()
    fdir.mkdir(parents=True, exist_ok=True)
    # Crash before commit: doc row exists, live dir missing -> move back.
    live = fdir / keep
    live.mkdir(parents=True, exist_ok=True)
    (live / "a.png").write_bytes(b"data-keep")
    live.rename(fdir / f".trash-{keep}")
    # Crash after commit: no doc row -> rmtree.
    live = fdir / gone
    live.mkdir(parents=True, exist_ok=True)
    (live / "b.png").write_bytes(b"data-gone")
    live.rename(fdir / f".trash-{gone}")
    con = db.connect()
    try:
        con.execute("DELETE FROM docs WHERE id=?", (gone,))
        con.commit()
    finally:
        con.close()
    # Ambiguous: doc row and live dir both present -> leave + warn.
    live = fdir / both
    live.mkdir(parents=True, exist_ok=True)
    (live / "live.png").write_bytes(b"live")
    stale = fdir / f".trash-{both}"
    stale.mkdir(parents=True, exist_ok=True)
    (stale / "stale.png").write_bytes(b"stale")

    assert backend_main.reap_trash_dirs() == {"restored": 1, "removed": 1, "skipped": 1}
    assert (fdir / keep / "a.png").read_bytes() == b"data-keep"
    assert not (fdir / f".trash-{keep}").exists()
    assert not (fdir / f".trash-{gone}").exists()
    assert (fdir / both / "live.png").read_bytes() == b"live"
    assert (stale / "stale.png").read_bytes() == b"stale"


def test_drag_to_trash_is_idempotent_and_restorable(c):
    register_user(c, "alice")
    did = make_doc(c, "Drag trash")
    for _ in range(2):
        response = c.post(f"/api/docs/{did}/trash")
        assert response.status_code == 200
        assert response.json() == {"trashed": True}
    assert c.get(f"/api/docs/{did}").status_code == 410
    assert c.post(f"/api/docs/{did}/restore").status_code == 200
    assert c.get(f"/api/docs/{did}").json()["title"] == "Drag trash"


def test_drag_to_trash_cannot_delete_someone_elses_document(c):
    register_user(c, "alice")
    did = make_doc(c, "Private drag")
    register_user(c, "bob")
    assert c.post(f"/api/docs/{did}/trash").status_code == 404
    login(c, "alice")
    assert c.get(f"/api/docs/{did}").status_code == 200


def test_restore_file_quota_neutral_at_cap(c, monkeypatch):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "RestoreCap")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("big.bin", b"0123456789")}).status_code == 200
    assert c.delete(f"/api/docs/{did}/files/big.bin").status_code == 200
    used = quota.user_bytes("alice")  # includes the 10 bytes parked in trash
    monkeypatch.setattr(quota, "quota_cap", lambda: used)
    entry = _trash_for(c, "big.bin")[0]
    # Restore is quota-neutral: without the delta the 10 in-trash bytes
    # double-count and push the restore over cap (413).
    assert c.post(f"/api/trash/{entry['id']}/restore").status_code == 200, None
    assert c.get(f"/api/docs/{did}/files/big.bin").content == b"0123456789"


def test_permanent_doc_delete_purges_file_trash(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Endgueltig")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("note.txt", b"data")}).status_code == 200
    assert c.delete(f"/api/docs/{did}/files/note.txt").status_code == 200
    assert _trash_for(c, "note.txt")
    assert c.delete(f"/api/docs/{did}").json()["trashed"] is True
    assert c.delete(f"/api/docs/{did}").json()["trashed"] is False
    # files/comments cascade with the doc; its trash copies must not live on
    assert _trash_for(c, "note.txt") == []


def test_restore_after_hard_deleted_doc_410(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Geist")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("ghost.txt", b"x")}).status_code == 200
    assert c.delete(f"/api/docs/{did}/files/ghost.txt").status_code == 200
    entry = _trash_for(c, "ghost.txt")[0]
    # Legacy ghost entry (purge runs on permanent delete; manufacture one
    # directly): restore must fail sensibly, not with "restore it first".
    con = db.connect()
    try:
        con.execute("DELETE FROM docs WHERE id=?", (did,))
        con.commit()
    finally:
        con.close()
    r = c.post(f"/api/trash/{entry['id']}/restore")
    assert r.status_code == 410, r.text


def test_project_hard_delete_purges_resource_trash(c):
    register_user(c, "alice")
    login(c, "alice")
    pid = c.post("/api/projects", json={"title": "Bibliothek"}).json()["id"]
    r = c.post(f"/api/projects/{pid}/resources", json={"name": "vals.typ", "content": "x=1\n"})
    assert r.status_code == 200, r.text
    version = next(v for v in c.get(f"/api/projects/{pid}/resources").json()["resources"]
                   if v["name"] == "vals.typ")["updated_at"]
    assert c.delete(f"/api/projects/{pid}/resources/vals.typ", params={"version": version}).status_code == 200
    assert [t for t in c.get("/api/docs").json()["trash"] if t["title"] == "vals.typ"]
    # no documents ever existed: the project hard-deletes with its library,
    # so the archived resource copy could never land anywhere again
    assert c.delete(f"/api/projects/{pid}").json()["ok"] is True
    assert [t for t in c.get("/api/docs").json()["trash"] if t["title"] == "vals.typ"] == []
