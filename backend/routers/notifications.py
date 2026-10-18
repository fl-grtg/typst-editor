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

from fastapi import APIRouter, Depends, Request

from backend import db, deps
from backend.services import notifications

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
