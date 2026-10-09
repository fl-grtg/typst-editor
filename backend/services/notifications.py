"""Minimal backend write path for notifications (no UI in Wave 1).

Follow-up 3D owns the inbox UI + routers/notifications.py; it reads the
table below and calls mark_read(). Every creation also emits a
"notification" event on the existing SSE channel (same transport).
"""
from __future__ import annotations

import sqlite3

from fastapi import HTTPException

from backend import db
from backend.services.sidebar import emit

NOTIF_TYPES = ("comment", "file", "member", "share", "system")


def create_notification(recipient: str, ntype: str, doc_id: str, text: str) -> str:
    """Insert + wake the recipient's streams. Returns the id."""
    if ntype not in NOTIF_TYPES:
        ntype = "system"
    nid, now = db.new_id("n_"), db.now_iso()
    con = db.connect()
    try:
        if not con.execute("SELECT 1 FROM users WHERE name=?", (recipient,)).fetchone():
            raise HTTPException(400, "Unknown recipient")
        try:
            con.execute("INSERT INTO notifications (id, recipient, type, doc_id, text, is_read, created_at) "
                        "VALUES (?,?,?,?,?,0,?)", (nid, recipient, ntype, doc_id or "", text[:2000], now))
            con.commit()
        except sqlite3.OperationalError as e:
            from backend import deps as _deps
            raise _deps.busy_503("create_notification", e) from e
    finally:
        con.close()
    emit(recipient, "notification", doc_id or "")
    return nid


def mark_read(nid: str, user: str) -> bool:
    """True when a row was marked (only the recipient's own)."""
    con = db.connect()
    try:
        cur = con.execute("UPDATE notifications SET is_read=1 WHERE id=? AND recipient=?", (nid, user))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def unread_count(user: str) -> int:
    con = db.connect()
    try:
        r = con.execute("SELECT COUNT(*) AS n FROM notifications WHERE recipient=? AND is_read=0",
                        (user,)).fetchone()
        return int(r["n"] or 0)
    finally:
        con.close()
