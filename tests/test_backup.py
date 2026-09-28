import io
import os
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path
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


def _init_cli_datadir(tmp_path, monkeypatch):
    data_dir = tmp_path / "cli-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db, "DB_PATH", data_dir / "app.db")
    db.init_db()
    return data_dir


def _run_backup_cli(*args, data_dir):
    root = Path(__file__).resolve().parent.parent
    env = dict(os.environ, DATA_DIR=str(data_dir))
    return subprocess.run([sys.executable, "scripts/backup.py", *args],
                          cwd=root, env=env, capture_output=True, text=True, timeout=60)


def test_backup_cli_dry_run(tmp_path, monkeypatch):
    data_dir = _init_cli_datadir(tmp_path, monkeypatch)
    r = _run_backup_cli("--dry-run", data_dir=data_dir)
    assert r.returncode == 0, r.stderr
    bdir = data_dir / "backup"
    dbs = list(bdir.glob("app-*.db")) if bdir.exists() else []
    assert dbs == []


def test_backup_cli_keep_zero_keeps_one(tmp_path, monkeypatch):
    # Guard in scripts/backup.py: keep = max(1, keep) -> --keep 0 behaelt 1.
    data_dir = _init_cli_datadir(tmp_path, monkeypatch)
    bdir = data_dir / "backup"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "app-20200101-000000.db").write_bytes(b"x")
    (bdir / "app-20200102-000000.db").write_bytes(b"x")
    r = _run_backup_cli("--keep", "0", data_dir=data_dir)
    assert r.returncode == 0, r.stderr
    dbs = sorted(bdir.glob("app-*.db"))
    assert len(dbs) == 1


def test_backup_cli_no_include_files(tmp_path, monkeypatch):
    data_dir = _init_cli_datadir(tmp_path, monkeypatch)
    (data_dir / "files").mkdir(parents=True, exist_ok=True)
    (data_dir / "files" / "a.txt").write_text("hi")
    r = _run_backup_cli("--no-include-files", data_dir=data_dir)
    assert r.returncode == 0, r.stderr
    bdir = data_dir / "backup"
    assert len(list(bdir.glob("app-*.db"))) == 1
    assert list(bdir.glob("app-*-files.tar.gz")) == []
