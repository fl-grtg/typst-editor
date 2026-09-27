import io
import os
import sqlite3
import time
import zipfile
from types import SimpleNamespace

from conftest import login, make_doc, register_user

from backend import config as backend_config
from backend import db
from backend import main as backend_main


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
    # Design: no 403 — everyone gets only their own docs (foreign ones missing).
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    make_doc(c, "AlicesDoc", content="a")
    login(c, "bob")
    r = c.get("/api/export.zip")
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert not any("AlicesDoc" in n for n in names)


def test_export_zip_headers(c):
    register_user(c, "alice")
    make_doc(c, "Backup", content="inhalt")
    r = c.get("/api/export.zip")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/zip")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "typst-backup.zip" in cd
    assert r.content[:2] == b"PK"


def test_export_leaves_no_tmp(c):
    register_user(c, "alice")
    make_doc(c, "Backup", content="inhalt")
    r = c.get("/api/export.zip")
    assert r.status_code == 200
    parent = backend_main.FILES_DIR.parent
    assert list(parent.glob("tmp*.zip")) == []
    assert list(parent.glob("*.tmp.*")) == []


def test_prune_old_exports(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    exp = data_dir / "exports"
    exp.mkdir(parents=True)
    old_job = exp / "job_old.zip"
    new_job = exp / "job_new.zip"
    other = exp / "notes.txt"
    old_tmp = data_dir / "tmpOld123.zip"
    new_tmp = data_dir / "tmpNew123.zip"
    for p in (old_job, new_job, other, old_tmp, new_tmp):
        p.write_bytes(b"x")
    now = time.time()
    old_ts = now - 25 * 3600
    os.utime(old_job, (old_ts, old_ts))
    os.utime(other, (old_ts, old_ts))  # other stays despite age (wrong pattern)
    os.utime(old_tmp, (old_ts, old_ts))
    monkeypatch.setattr(backend_config, "load", lambda: SimpleNamespace(DATA_DIR=data_dir))
    backend_main.prune_old_exports()
    assert not old_job.exists()
    assert not old_tmp.exists()
    assert new_job.is_file()
    assert new_tmp.is_file()
    assert other.is_file()


def test_backup_to_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "isolated" / "app.db")
    db.init_db()
    con = db.connect()
    try:
        con.execute("INSERT INTO users (name, hash) VALUES (?,?)", ("u1", "x"))
        con.commit()
    finally:
        con.close()
    target = tmp_path / "deep" / "level" / "backup.db"
    db.backup_to(target)
    assert target.is_file()
    bcon = sqlite3.connect(str(target))
    try:
        assert bcon.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = {r[0] for r in bcon.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"users", "docs"} <= tables
        assert bcon.execute("SELECT COUNT(*) FROM users WHERE name='u1'").fetchone()[0] == 1
    finally:
        bcon.close()
