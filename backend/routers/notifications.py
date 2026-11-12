"""Topbar summary: unread notifications plus open review packages by others.

#6 (round 4): the client dots-list polls GET /api/notifications/summary.
Contract (additive; new endpoint, nothing else changes):
  unread: int             recipient's unconfirmed notifications
  package_total: int      matching open packages by others (uncapped)
  packages: [{project, project title?, id, title, author, updated_at}]
                          newest first, at most 50 entries
Open means packages with remaining files (json_array_length(files)>0),
the same predicate the proposals list uses; author != requester keeps the
package visible for exactly the users it needs a decision from Scope:
projects the user is a member of (owner row or project_members, including
reviewer-only readers).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend import db, deps
from backend.services import notifications, projects

router = APIRouter()

PACKAGES_CAP = 50  # payload bound; package_total reports the uncapped count


@router.get("/api/notifications/summary")
def notification_summary(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")  # polled like a list read, light bucket
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT s.id, s.project_id AS project, p.title AS project_title, s.title, "
            "s.author, s.author_name, s.updated_at FROM suggestion_packages s"
            " JOIN projects p ON p.id=s.project_id"
            " WHERE p.archived=0 AND s.author<>? AND json_array_length(s.files)>0"
            " AND (p.owner=? OR EXISTS(SELECT 1 FROM project_members m"
            " WHERE m.project_id=s.project_id AND m.username=?))"
            " ORDER BY s.updated_at DESC, s.id DESC",
            (user, user, user),
        ).fetchall()
    finally:
        con.close()
    found = [dict(r) for r in rows]
    return {
        "unread": notifications.unread_count(user),
        "package_total": len(found),
        "packages": found[:PACKAGES_CAP],
    }


LIST_CAP = 50


@router.get("/api/notifications")
def list_notifications(req: Request, user: str = Depends(deps.me)) -> dict:
    """Inbox items, newest first (at most LIST_CAP), with the project title."""
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT n.id, n.type, n.project_id, p.title AS project_title, n.doc_id, "
            "COALESCE(c.parent_id, n.ref) AS ref, n.text, n.actor, n.is_read, n.created_at"
            " FROM notifications n LEFT JOIN projects p ON p.id=n.project_id"
            " LEFT JOIN comments c ON c.id=n.ref"
            " WHERE n.recipient=? ORDER BY n.created_at DESC, n.rowid DESC LIMIT ?", (user, LIST_CAP)).fetchall()
    finally:
        con.close()
    return {"unread": notifications.unread_count(user), "items": [{**dict(r), "is_read": bool(r["is_read"])} for r in rows]}


@router.post("/api/notifications/read-all")
def read_all(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    return {"marked": notifications.mark_all_read(user)}


@router.post("/api/notifications/{nid}/read")
def read_one(nid: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    return {"ok": notifications.mark_read(nid, user)}


@router.delete("/api/notifications")
def clear_notifications(req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    return {"deleted": notifications.clear_all(user)}


@router.delete("/api/notifications/{nid}")
def delete_notification(nid: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    return {"ok": notifications.delete_one(nid, user)}


class WatchSet(BaseModel):
    level: str


def _watch_state(con, project_id: str, user: str) -> dict:
    row = con.execute("SELECT level,seen_at FROM project_watch WHERE project_id=? AND username=?", (project_id, user)).fetchone()
    seen = row["seen_at"] if row else ""
    # change screen base: newest checkpoint up to the last look, else the oldest one
    base = con.execute("SELECT id FROM project_snapshots WHERE project_id=? AND created_at<=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (project_id, seen)).fetchone() if seen else None
    base = base or con.execute("SELECT id FROM project_snapshots WHERE project_id=? ORDER BY created_at,rowid LIMIT 1", (project_id,)).fetchone()
    return {"level": row["level"] if row else notifications.DEFAULT_LEVEL, "seen_at": seen, "base": base["id"] if base else None}


@router.get("/api/watch")
def list_watch(req: Request, user: str = Depends(deps.me)) -> dict:
    """Watch level for every project the user belongs to (inbox settings)."""
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        rows = con.execute(
            "SELECT p.id, p.title FROM projects p WHERE p.archived=0 AND (p.owner=? OR EXISTS("
            "SELECT 1 FROM project_members m WHERE m.project_id=p.id AND m.username=?)) ORDER BY p.title COLLATE NOCASE", (user, user)).fetchall()
        return {"projects": [{"project_id": r["id"], "title": r["title"], "level": notifications.watch_level(con, r["id"], user)} for r in rows]}
    finally:
        con.close()


@router.get("/api/projects/{project_id}/watch")
def get_watch(project_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        projects.require(con, project_id, user)
        return _watch_state(con, project_id, user)
    finally:
        con.close()


@router.put("/api/projects/{project_id}/watch")
def set_watch(project_id: str, b: WatchSet, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "comments")
    if b.level not in notifications.LEVELS:
        raise HTTPException(400, "Unknown watch level")
    with db.tx() as con:
        projects.require(con, project_id, user)
        con.execute("INSERT INTO project_watch(project_id,username,level,seen_at) VALUES (?,?,?,?) "
                    "ON CONFLICT(project_id,username) DO UPDATE SET level=excluded.level", (project_id, user, b.level, db.now_iso()))
        return _watch_state(con, project_id, user)


@router.post("/api/projects/{project_id}/watch/seen")
def mark_seen(project_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    """The user looked at the changes: move the baseline to now and clear the project's "changes" items."""
    deps.limited(req, "comments")
    with db.tx() as con:
        projects.require(con, project_id, user)
        level = notifications.watch_level(con, project_id, user)
        con.execute("INSERT INTO project_watch(project_id,username,level,seen_at) VALUES (?,?,?,?) "
                    "ON CONFLICT(project_id,username) DO UPDATE SET seen_at=excluded.seen_at", (project_id, user, level, db.now_iso()))
        con.execute("UPDATE notifications SET is_read=1 WHERE recipient=? AND type='changes' AND project_id=?", (user, project_id))
    return {"ok": True}
