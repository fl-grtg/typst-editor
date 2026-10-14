"""Automatic version snapshots and pruning."""
from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from backend import db, deps
from backend.constants import SNAP_EVERY, SNAP_MAX

log = logging.getLogger("typst.main")


def prune_snaps(con: sqlite3.Connection, doc_id: str) -> None:
    con.execute("DELETE FROM snapshots WHERE doc_id=? AND id NOT IN "
                "(SELECT id FROM snapshots WHERE doc_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?)",
                (doc_id, doc_id, SNAP_MAX))


def auto_snap(doc_id: str, content: str, label: str = "") -> None:
    con = db.connect()
    try:
        try:
            con.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as e:
            log.warning("auto_snap %s busy, skipped: %s", doc_id, e)
            return
        try:
            last = con.execute("SELECT created_at FROM snapshots WHERE doc_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                               (doc_id,)).fetchone()
            cut = (datetime.now(UTC) - timedelta(seconds=SNAP_EVERY)).isoformat()
            if label or not last or last["created_at"] < cut:
                row = con.execute("SELECT owner FROM docs WHERE id=?", (doc_id,)).fetchone()
                if row:
                    try:
                        deps.check_quota(row["owner"], len(content.encode("utf-8")))
                    except HTTPException:
                        con.execute("ROLLBACK")
                        raise
                con.execute("INSERT INTO snapshots (id, doc_id, content, label, created_at) VALUES (?,?,?,?,?)",
                            (db.new_id("s_"), doc_id, content, label, db.now_iso()))
                prune_snaps(con, doc_id)
                con.commit()
            else:
                con.execute("ROLLBACK")
        except HTTPException:
            raise
        except sqlite3.OperationalError as e:
            log.warning("auto_snap %s failed: %s", doc_id, e)
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
    finally:
        con.close()
