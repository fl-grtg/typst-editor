from conftest import login, make_doc, register_user

from backend import db
from backend import main as backend_main


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
