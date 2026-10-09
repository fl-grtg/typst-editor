"""Wave 1 FIX-ALL round, track 1D: G4-1 (duplicate quota), G4-2 (parallel
start race), G4-3 (scan robustness), G4-Oracle (trash read-token 404)."""
import os
import pathlib
import sqlite3
import threading
from contextlib import contextmanager
from types import SimpleNamespace

from conftest import login, make_doc, register_user

from backend import config as backend_config
from backend import db, deps
from backend.services import quota as quota_svc


def _v12_db(tmp_path, monkeypatch):
    """Returning DB in v12 state (files/notifications/read_tokens dropped)."""
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
    return tmp_path / "old.db"


def _cap_config(monkeypatch, **over):
    real = backend_config.load()
    monkeypatch.setattr(backend_config, "load",
                        lambda: SimpleNamespace(**{**vars(real), **over}))


def test_duplicate_nested_files_count_toward_max_files(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Tief")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("a.png", b"1")}).status_code == 200
    assert c.post(f"/api/docs/{did}/files", files={"f": ("sub/b.png", b"22")}).status_code == 200
    assert c.post(f"/api/docs/{did}/files", files={"f": ("sub/deep/c.png", b"333")}).status_code == 200
    before = {d["id"] for d in c.get("/api/docs").json()["own"]}
    _cap_config(monkeypatch, MAX_FILES_PER_DOC=2)
    r = c.post(f"/api/docs/{did}/duplicate")
    assert r.status_code == 400, r.text  # 3 nested files > 2: top-level-only count would pass
    assert {d["id"] for d in c.get("/api/docs").json()["own"]} == before


def test_duplicate_nested_bytes_count_toward_quota(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "TiefQ", content="hi")  # 2 bytes content
    assert c.post(f"/api/docs/{did}/files", files={"f": ("top.png", b"t" * 10)}).status_code == 200
    assert c.post(f"/api/docs/{did}/files", files={"f": ("sub/nested.png", b"n" * 100)}).status_code == 200
    base = quota_svc.user_bytes("alice")
    # Extra under the new recursive count: 2 + 10 + 100 = 112. A top-level
    # count would see 2 + 10 = 12 and pass; 112 > 111 must fail pre-copy.
    monkeypatch.setattr(quota_svc, "quota_cap", lambda: base + 111)
    r = c.post(f"/api/docs/{did}/duplicate")
    assert r.status_code == 413, r.text


def test_duplicate_over_quota_rolls_back_no_orphan(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "RennQuota", content="hallo")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("sub/big.png", b"b" * 200)}).status_code == 200
    before_ids = {d["id"] for d in c.get("/api/docs").json()["own"]}
    before_dirs = {p.name for p in deps.get_files_dir().iterdir()}
    base = quota_svc.user_bytes("alice")
    # Race simulation: pre-check sees room, post-copy verdict sees quota
    # full (a concurrent writer filled it in the gap). First quota_cap call
    # (pre-check) passes, every later one (post-copy) fails.
    calls = []

    def _shrinking_cap():
        calls.append(1)
        return 10 ** 12 if len(calls) == 1 else base

    monkeypatch.setattr(quota_svc, "quota_cap", _shrinking_cap)
    r = c.post(f"/api/docs/{did}/duplicate")
    assert r.status_code == 413, r.text
    assert len(calls) >= 2  # both verdicts actually ran
    # No orphan: same docs, same dirs, no dangling files-table rows.
    assert {d["id"] for d in c.get("/api/docs").json()["own"]} == before_ids
    assert {p.name for p in deps.get_files_dir().iterdir()} == before_dirs
    con = db.connect()
    try:
        assert con.execute("SELECT COUNT(*) AS n FROM files "
                           "WHERE doc_id NOT IN (SELECT id FROM docs)").fetchone()["n"] == 0
    finally:
        con.close()


def test_duplicate_quota_rollback_db_locked_keeps_copy(c, monkeypatch):
    # Row DELETE stuck on a transient lock: the tree must NOT go while the
    # row survives (that would orphan it), so the copy stays (fail-open).
    register_user(c, "alice")
    did = make_doc(c, "LockRb", content="hallo")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("a.png", b"1" * 50)}).status_code == 200
    base = quota_svc.user_bytes("alice")
    calls = []

    def _shrinking_cap():
        calls.append(1)
        return 10 ** 12 if len(calls) == 1 else base

    monkeypatch.setattr(quota_svc, "quota_cap", _shrinking_cap)
    real_tx = db.tx
    tx_calls = []

    @contextmanager
    def _flaky_tx():
        tx_calls.append(1)
        if len(tx_calls) >= 2:  # insert went through; rollback DELETE hangs
            raise sqlite3.OperationalError("database is locked")
        with real_tx() as con:
            yield con

    monkeypatch.setattr(db, "tx", _flaky_tx)
    r = c.post(f"/api/docs/{did}/duplicate")
    assert r.status_code == 200, r.text
    nid = r.json()["id"]
    assert c.get(f"/api/docs/{nid}").status_code == 200
    assert (deps.get_files_dir() / nid / "a.png").is_file()


def test_parallel_init_db_single_v13_and_backup(tmp_path, monkeypatch):
    _v12_db(tmp_path, monkeypatch)
    fdir = tmp_path / "files" / "d_x"
    fdir.mkdir(parents=True)
    (fdir / "a.png").write_bytes(b"1234567890")
    (fdir / "sub").mkdir()
    (fdir / "sub" / "b.typ").write_text("hi")
    # Rendezvous both starters after the pending-read, before either step
    # commits: guarantees the v13 INSERT collides like in production.
    barrier = threading.Barrier(2, timeout=30)
    real_backup = db.backup_before_migrate

    def _sync_backup(con, done):
        barrier.wait(timeout=30)
        return real_backup(con, done)

    monkeypatch.setattr(db, "backup_before_migrate", _sync_backup)
    errors = []

    def _run():
        try:
            db.init_db()
        except Exception as e:  # noqa: BLE001 - collected and asserted below
            errors.append(e)

    threads = [threading.Thread(target=_run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not any(t.is_alive() for t in threads)
    assert errors == []
    con = db.connect()
    try:
        assert con.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"] == 13
        assert con.execute("SELECT COUNT(*) AS n FROM schema_version WHERE v=13").fetchone()["n"] == 1
        assert con.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"] == 2
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()
    assert len(list(tmp_path.glob("old-migrate-*.db"))) >= 1


def test_migrate_v13_skips_broken_files_and_symlinks(tmp_path, monkeypatch):
    _v12_db(tmp_path, monkeypatch)
    fdir = tmp_path / "files" / "d_x"
    fdir.mkdir(parents=True)
    (fdir / "good.png").write_bytes(b"12345")
    (fdir / "sub").mkdir()
    (fdir / "sub" / "ok.typ").write_text("hi")
    (fdir / "boom.png").write_bytes(b"unreadable")  # stat() will raise below
    (fdir / "link.png").symlink_to(fdir / "good.png")  # file symlink: skipped
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"s" * 40)
    (fdir / "extdir").symlink_to(outside, target_is_directory=True)  # dir symlink: not descended
    try:
        raw = os.path.join(os.fsencode(str(fdir)), b"bad\xffname.png")
        with open(raw, "wb") as fh:
            fh.write(b"zzz")
    except OSError:
        pass  # platform cannot do surrogate names: rest of the test still applies
    real_stat = pathlib.Path.stat

    def _flaky_stat(self, *a, **k):
        if self.name == "boom.png":
            raise OSError("simulated I/O error")
        return real_stat(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "stat", _flaky_stat)
    con = db.connect()
    try:
        db.migrate(con)  # must not raise
        con.commit()
        paths = {r["path"] for r in con.execute("SELECT path FROM files").fetchall()}
    finally:
        con.close()
    assert paths == {"good.png", "sub/ok.typ"}


def test_read_token_trash_returns_404_like_invalid(c):
    register_user(c, "alice")
    did = make_doc(c, "Oracle", content="x")
    tok = c.post(f"/api/docs/{did}/read-token", json={}).json()["token"]
    assert c.delete(f"/api/docs/{did}").status_code == 200  # trash
    login(c, "alice")  # fresh session still owns; read link needs none
    c.post("/api/logout")
    assert c.get(f"/api/r/{tok}").status_code == 404
    assert c.get("/api/r/does-not-exist").status_code == 404
