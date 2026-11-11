"""Inbox notifications: write path, watch levels and the producers.

Types: mention (someone wrote @you), proposal (a change package in a project you follow),
changes (the project changed; shown with the change screen). Recipients are chosen by the
per-project watch level: mentions < proposals (default) < all. Mentions always reach the
person mentioned. No e-mail and no browser push: the inbox is the only channel.
Every creation also emits a "notification" event on the existing SSE channel.
"""
from __future__ import annotations

import logging
import re
import sqlite3

from fastapi import HTTPException

from backend import db
from backend.services.sidebar import emit

log = logging.getLogger("typst.notifications")

NOTIF_TYPES = ("comment", "file", "member", "share", "system", "mention", "proposal", "changes")
LEVELS = ("mentions", "proposals", "all")
DEFAULT_LEVEL = "proposals"
MENTION = re.compile(r"(?<![\w@])@([\w-]{1,64})")

_last_editor: dict[str, str] = {}  # best effort: who wrote to a project last (no self-notification)


def note_editor(project_id: str, user: str) -> None:
    if len(_last_editor) > 5000:
        _last_editor.clear()
    _last_editor[project_id] = user


def last_editor(project_id: str) -> str:
    return _last_editor.get(project_id, "")


def create_notification(recipient: str, ntype: str, doc_id: str, text: str, project_id: str = "",
                        ref: str = "", actor: str = "", coalesce: bool = False) -> str:
    """Insert + wake the recipient's streams. Returns the id.

    coalesce: an unread item of the same type/project/ref is refreshed instead of adding another row.
    """
    if ntype not in NOTIF_TYPES:
        ntype = "system"
    nid, now = db.new_id("n_"), db.now_iso()
    con = db.connect()
    try:
        if not con.execute("SELECT 1 FROM users WHERE name=?", (recipient,)).fetchone():
            raise HTTPException(400, "Unknown recipient")
        try:
            row = con.execute("SELECT id FROM notifications WHERE recipient=? AND type=? AND project_id=? AND ref=? AND is_read=0",
                              (recipient, ntype, project_id, ref)).fetchone() if coalesce else None
            if row:
                nid = row["id"]
                con.execute("UPDATE notifications SET text=?, actor=?, doc_id=?, created_at=? WHERE id=?",
                            (text[:2000], actor, doc_id or "", now, nid))
            else:
                con.execute("INSERT INTO notifications (id, recipient, type, doc_id, text, is_read, created_at, project_id, ref, actor) "
                            "VALUES (?,?,?,?,?,0,?,?,?,?)", (nid, recipient, ntype, doc_id or "", text[:2000], now, project_id, ref, actor))
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


def mark_all_read(user: str) -> int:
    con = db.connect()
    try:
        cur = con.execute("UPDATE notifications SET is_read=1 WHERE recipient=? AND is_read=0", (user,))
        con.commit()
        return cur.rowcount
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


# --- watch levels ---------------------------------------------------------------------------

def watch_level(con: sqlite3.Connection, project_id: str, user: str) -> str:
    r = con.execute("SELECT level FROM project_watch WHERE project_id=? AND username=?", (project_id, user)).fetchone()
    return r["level"] if r else DEFAULT_LEVEL


def watchers(project_id: str, at_least: str, exclude: set[str] | frozenset[str] = frozenset()) -> list[str]:
    """Members (owner included) whose watch level reaches `at_least`."""
    need = LEVELS.index(at_least)
    con = db.connect()
    try:
        p = con.execute("SELECT owner FROM projects WHERE id=?", (project_id,)).fetchone()
        if not p:
            return []
        people = [p["owner"], *[r[0] for r in con.execute("SELECT username FROM project_members WHERE project_id=?", (project_id,))]]
        return [u for u in dict.fromkeys(people) if u not in exclude and LEVELS.index(watch_level(con, project_id, u)) >= need]
    finally:
        con.close()


def _safely(label: str, fn, *a, **kw) -> None:
    """Notifications never break the action that caused them."""
    try:
        fn(*a, **kw)
    except (HTTPException, sqlite3.Error, OSError) as e:
        log.warning("%s skipped: %s", label, e)


# --- producers --------------------------------------------------------------------------------

def mention_names(text: str) -> set[str]:
    return {m.group(1).lower() for m in MENTION.finditer(text or "")}


def _notify_mentions(doc_id: str, author: str, text: str, ref: str, before: str = "") -> None:
    """@name in a comment: reaches people with access to the doc (new mentions only when editing)."""
    from backend.services.sidebar import doc_users
    names = mention_names(text) - mention_names(before)
    if not names:
        return
    con = db.connect()
    try:
        d = con.execute("SELECT project_id FROM docs WHERE id=?", (doc_id,)).fetchone()
    finally:
        con.close()
    project_id = d["project_id"] if d else ""
    for user in doc_users(doc_id):
        if user != author and user.lower() in names:
            _safely("mention", create_notification, user, "mention", doc_id, text.strip()[:140], project_id, ref, author)


def _notify_proposal(project_id: str, author: str, package_id: str, title: str) -> None:
    for user in watchers(project_id, "proposals", {author}):
        _safely("proposal", create_notification, user, "proposal", "", title[:140], project_id, package_id, author, True)


def _notify_changes(project_id: str, skip: set[str] | frozenset[str] = frozenset()) -> None:
    """Level "all": one refreshed, unread item per person and project ("changes since you last looked")."""
    editor = last_editor(project_id)
    for user in watchers(project_id, "all", {editor, *skip} - {""}):
        _safely("changes", create_notification, user, "changes", "", "", project_id, "", editor, True)


def notify_mentions(*a, **kw) -> None:
    _safely("mentions", _notify_mentions, *a, **kw)


def notify_proposal(*a, **kw) -> None:
    _safely("proposal", _notify_proposal, *a, **kw)


def notify_changes(*a, **kw) -> None:
    _safely("changes", _notify_changes, *a, **kw)
