"""Startup maintenance: trash directory sweep."""
from __future__ import annotations

import logging
import shutil

from backend import db, deps

log = logging.getLogger("typst.main")


def reap_trash_dirs() -> dict[str, int]:
    # B8: delete_me renames FILES_DIR/<id> aside to .trash-<id> before the DB
    # tx. A crash between the steps leaves orphans that user_bytes never
    # counts (and backup still tars). Sweep them at startup (shallow, fast).
    counts = {"restored": 0, "removed": 0, "skipped": 0}
    try:
        entries = list(deps.get_files_dir().iterdir())
    except OSError as e:
        log.warning("trash sweep list failed: %s", e)
        return counts
    trash = [p for p in entries if p.name.startswith(".trash-")]
    # B9: duplicate stages file trees in .tmp.dup-<id> before the atomic
    # rename; a crash between copytree and os.replace orphans the staging
    # dir (invisible to quota/list walks via the ".tmp." rule). Sweep them
    # here: they are never a publish target, only garbage.
    for p in entries:
        if p.name.startswith(".tmp.dup-"):
            try:
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
            except OSError as e:
                log.warning("trash sweep skipping %s: %s", p.name, e)
                counts["skipped"] += 1
            else:
                counts["removed"] += 1
    if not trash:
        return counts
    con = db.connect()
    try:
        for dst in trash:
            did = dst.name[len(".trash-"):]
            if not did or not dst.is_dir():
                # Stray file, not a staged doc dir: remove it, don't re-warn forever.
                try:
                    dst.unlink()
                except OSError as e:
                    log.warning("trash sweep skipping %s: %s", dst.name, e)
                    counts["skipped"] += 1
                else:
                    counts["removed"] += 1
                continue
            live = deps.get_files_dir() / did
            row = con.execute("SELECT 1 FROM docs WHERE id=?", (did,)).fetchone()
            if row is not None and not live.exists():
                try:
                    dst.rename(live)
                except OSError as e:
                    log.warning("trash sweep restore %s failed: %s", did, e)
                    counts["skipped"] += 1
                else:
                    counts["restored"] += 1
            elif row is None:
                try:
                    shutil.rmtree(dst)
                    if dst.exists():
                        raise OSError("rmtree left files behind")
                except OSError as e:
                    log.warning("trash sweep remove %s failed: %s", did, e)
                    counts["skipped"] += 1
                else:
                    counts["removed"] += 1
            else:
                log.warning("trash sweep leaving ambiguous %s (doc and files both present)", did)
                counts["skipped"] += 1
    finally:
        con.close()
    return counts
