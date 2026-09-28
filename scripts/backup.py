"""SQLite backup via VACUUM INTO (consistent under WAL) plus files/ archive. Read-only, never replaces live data."""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tarfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import config, db  # noqa: E402


def _chmod_600(p: Path) -> None:
    # Backups hold the full DB (sessions, hashes): owner-only, even though
    # chmod is no substitute for encryption (see --encrypt hint in epilog).
    try:
        os.chmod(p, 0o600)
    except OSError as e:
        print("warning: chmod 600 failed for %s: %s" % (p, e), file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Writes DATA_DIR/backup/app-YYYYMMDD-HHMMSS.db (VACUUM INTO) plus a files/ archive next to it.",
        epilog="Backups are chmod 600 but UNENCRYPTED (there is no --encrypt flag by design: "
               "use your own key management). Encrypt after creation, then delete the plaintext, e.g.: "
               "age --encrypt -r <recipient> -o <file>.age <file>  or:  gpg --symmetric --cipher-algo AES256 <file>",
    )
    ap.add_argument("--keep", type=int, default=7, help="Keep the newest N backups (default: 7).")
    ap.add_argument("--include-files", dest="include_files", action=argparse.BooleanOptionalAction, default=True, help="Also archive DATA_DIR/files next to the DB (default: on).")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    cfg = config.load()
    bdir = cfg.DATA_DIR / "backup"
    base = "app-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    dest, n = bdir / (base + ".db"), 0
    while dest.exists():  # twice per second: -1, -2, ... instead of a VACUUM error
        n += 1
        dest = bdir / ("%s-%d.db" % (base, n))
    fdest = dest.with_name(dest.stem + "-files.tar.gz")
    print(dest, "dry-run" if a.dry_run else "")
    if a.include_files:
        print(fdest, "dry-run" if a.dry_run else "")
    if a.dry_run:
        return
    db.backup_to(dest)
    _chmod_600(dest)
    con = sqlite3.connect(str(dest))
    ok = con.execute("PRAGMA integrity_check").fetchone()[0]
    con.close()
    if ok != "ok":
        raise SystemExit("integrity_check failed: %s" % dest)
    if a.include_files:
        files = cfg.DATA_DIR / "files"
        with tarfile.open(fdest, "w:gz") as tar:
            if files.is_dir():
                tar.add(files, arcname="files")
        _chmod_600(fdest)
    for pattern in ("app-*.db", "app-*-files.tar.gz"):
        olds = sorted(bdir.glob(pattern))
        keep = max(1, a.keep)  # --keep 0 would purge all, keep at least 1
        olds = olds[:-keep]
        for p in olds:
            p.unlink(missing_ok=True)
    print(dest)


if __name__ == "__main__":
    main()
