"""Comment routes."""
from __future__ import annotations

import asyncio
import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request

from backend import db, deps
from backend.schemas import AnchorSet, CommentEdit, CommentNew, ResolveSet, SuggestionBatch, SuggestionNew
from backend.services import notifications, projects
from backend.services.sidebar import emit_doc

router = APIRouter()
log = logging.getLogger("typst.main")

# List payload only: the DB keeps the full suggestion_old (accept reads it
# there); oversized values just degrade here so N comments cannot ship
# 20 KB rows each.
_SUGGESTION_VIEW_CAP = 4000


def _need_package(con: sqlite3.Connection, doc_id: str, package_id: str, user: str) -> None:
    if not package_id:
        return
    row = con.execute(
        "SELECT d.project_id FROM docs d JOIN suggestion_packages p ON p.project_id=d.project_id "
        "WHERE d.id=? AND p.id=?", (doc_id, package_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Package not found")
    projects.require(con, row["project_id"], user)


def _suggestion_view(row: sqlite3.Row) -> dict:
    d = dict(row)
    # Uniqueness: the client matches suggestion_old verbatim against the
    # current text before accept, so an oversized value must degrade to ""
    # (client falls back to the anchor line + conflict hint) - a truncated
    # copy could double-match and fail the accept check.
    if d["suggestion_old"] and len(d["suggestion_old"]) > _SUGGESTION_VIEW_CAP:
        d["suggestion_old"] = ""
    if d["replacement"] and len(d["replacement"]) > _SUGGESTION_VIEW_CAP:
        d["replacement"] = d["replacement"][:_SUGGESTION_VIEW_CAP]  # render-only
    return d


@router.post("/api/docs/{doc_id}/suggestions")
def add_suggestion(doc_id: str, b: SuggestionNew, req: Request, user: str = Depends(deps.me)) -> dict:
    from backend.services import suggestions
    deps.check_doc_id(doc_id)
    deps.limited(req, "comments")
    return suggestions.create(user, doc_id, b)


@router.post("/api/docs/{doc_id}/suggestions/batch")
def add_suggestion_batch(doc_id: str, b: SuggestionBatch, req: Request, user: str = Depends(deps.me)) -> dict:
    from backend.services import suggestions
    deps.check_doc_id(doc_id)
    deps.limited(req, "comments")
    return {"suggestions": suggestions.create_batch(user, doc_id, b.changes)}


@router.post("/api/docs/{doc_id}/suggestions/{cid}/accept")
async def accept_suggestion(doc_id: str, cid: str, req: Request, user: str = Depends(deps.me)) -> dict:
    from backend import sync
    from backend.services import suggestions
    deps.check_doc_id(doc_id)
    deps.limited(req, "comments")
    room, update = await asyncio.to_thread(suggestions.accept, user, doc_id, cid)
    try:
        await sync.bcast(room["conns"], None, sync.blob(sync.write_var(sync.MSG_SYNC), sync.write_var(sync.UPDATE),
                                                     sync.write_var(len(update)), update))
    except Exception as e:
        log.warning("suggestion accept bcast: %s", e)
    return {"ok": True}


@router.post("/api/docs/{doc_id}/suggestions/{cid}/reject")
def reject_suggestion(doc_id: str, cid: str, req: Request, user: str = Depends(deps.me)) -> dict:
    from backend.services import suggestions
    deps.check_doc_id(doc_id)
    deps.limited(req, "comments")
    return suggestions.reject(user, doc_id, cid)


@router.get("/api/docs/{doc_id}/comments")
def list_comments(doc_id: str, req: Request, package_id: str = "", user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    pkg = package_id.strip()
    con = db.connect()
    try:
        _need_package(con, doc_id, pkg, user)
        rows = con.execute("SELECT id, username, author, anchor, quote, text, parent_id, resolved, created_at, "
                           "suggestion_old, replacement, suggestion_status, package_id, anchor_quote, anchor_range, "
                           "replaces_id, deleted FROM comments WHERE doc_id=? AND package_id=? ORDER BY created_at",
                           (doc_id, pkg)).fetchall()
        tops = []
        reps: dict[str, list] = {}
        changes = []
        for r in rows:
            d = _suggestion_view(r)
            d["deleted"] = bool(d["deleted"])
            if d["replaces_id"]:
                changes.append(d)
            elif d["parent_id"]:
                reps.setdefault(d["parent_id"], []).append(d)
            else:
                tops.append(d)
        ids = {t["id"] for t in tops}
        for t in tops:
            t["replies"] = reps.get(t["id"], [])
        for parent, replies in reps.items():
            if parent not in ids:
                changes.extend(replies)
        return {"comments": tops, "changes": changes} if pkg else {"comments": tops}
    finally:
        con.close()


@router.post("/api/docs/{doc_id}/comments")
def add_comment(doc_id: str, b: CommentNew, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "comments")
    role = deps.need_access(user, doc_id)
    text = "" if b.deleted else b.text.strip()
    if (not text and not b.replaces_id) or len(b.text) > 2000 or (b.deleted and not b.replaces_id):
        raise HTTPException(400, "Comment: 1-2000 chars")
    if b.anchor < 0:
        raise HTTPException(400, "Anchor < 0")
    cid = db.new_id("c_")
    ref = cid
    pkg = b.package_id.strip()
    existing = old = None
    with db.tx() as con:
        if b.replaces_id:
            if not pkg or b.parent_id:
                raise HTTPException(400, "Comment changes belong to a proposal")
            target = con.execute("SELECT username, parent_id, package_id, suggestion_status, text, resolved FROM comments WHERE id=? AND doc_id=?",
                                 (b.replaces_id, doc_id)).fetchone()
            if not target or target["package_id"] or target["suggestion_status"]:
                raise HTTPException(404, "Comment gone")
            if not b.deleted and not text and (target["parent_id"] or bool(target["resolved"]) == b.resolved):
                raise HTTPException(400, "Nothing to resolve")
            if target["username"] != user and not ((b.deleted or not text) and role == "owner"):
                raise HTTPException(403, "Only author or owner")
            old = target["text"]
        if b.parent_id:
            p = con.execute("SELECT parent_id, package_id, replaces_id FROM comments WHERE id=? AND doc_id=?",
                            (b.parent_id, doc_id)).fetchone()
            if not p:
                raise HTTPException(404, "Thread gone")
            if p["parent_id"] or p["replaces_id"]:
                raise HTTPException(400, "Nested replies not allowed")
            if p["package_id"]:
                if pkg and pkg != p["package_id"]:
                    raise HTTPException(400, "Reply belongs to another proposal")
                pkg = p["package_id"]
            if not pkg:
                # The inbox renders whole threads: point a live reply mention at the thread root.
                ref = b.parent_id
        _need_package(con, doc_id, pkg, user)
        if b.replaces_id:
            existing = con.execute("SELECT id FROM comments WHERE package_id=? AND replaces_id=?",
                                   (pkg, b.replaces_id)).fetchone()
            if existing:
                con.execute("UPDATE comments SET username=?, text=?, deleted=?, resolved=?, suggestion_old=? WHERE id=?",
                            (user, text, int(b.deleted), int(b.resolved), old, existing["id"]))
                cid = existing["id"]
        if not existing:
            q = b.quote[:500]
            anchor = max(1, b.anchor)  # 1-based (UI); 0 = top alias -> line 1
            con.execute(
                "INSERT INTO comments (id, doc_id, username, author, anchor, quote, text, parent_id, package_id, anchor_quote, "
                "anchor_range, replaces_id, deleted, resolved, suggestion_old, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, doc_id, user, "", anchor, q if q.strip() else "", text, b.parent_id, pkg,
                 b.anchor_quote, None if pkg or b.parent_id else b.anchor_range, b.replaces_id, int(b.deleted),
                 int(b.resolved and bool(b.replaces_id)), old, db.now_iso()),
            )
    if not b.replaces_id:
        notifications.notify_mentions(doc_id, user, text, ref)
    emit_doc(doc_id, "comment", exclude=user)
    return {"id": cid}


@router.delete("/api/docs/{doc_id}/comments/{cid}")
def delete_comment(doc_id: str, cid: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "comments")
    role = deps.need_access(user, doc_id)
    con = db.connect()
    try:
        t = con.execute("SELECT username, parent_id, suggestion_status, package_id FROM comments WHERE id=? AND doc_id=?",
                        (cid, doc_id)).fetchone()
        if not t:
            raise HTTPException(404, "Comment gone")
        _need_package(con, doc_id, t["package_id"], user)
        if role != "owner" and t["username"] != user:
            raise HTTPException(403, "Only author or owner")
        top = cid if not t["parent_id"] else t["parent_id"]
        a = con.execute("SELECT suggestion_status FROM comments WHERE id=?", (top,)).fetchone()
        if a and a["suggestion_status"] == "pending":
            raise HTTPException(400, "Use accept/reject for suggestions")
        if t["parent_id"]:
            con.execute("DELETE FROM comments WHERE id=?", (cid,))
        else:
            con.execute("DELETE FROM comments WHERE id=? OR parent_id=?", (cid, cid))
        con.commit()
        emit_doc(doc_id, "comment", exclude=user)
        return {"ok": True}
    finally:
        con.close()


@router.post("/api/docs/{doc_id}/comments/{cid}/anchor")
def move_comment(doc_id: str, cid: str, b: AnchorSet, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "files_list")  # background anchor shifts on edit: must not starve comment writes
    role = deps.need_access(user, doc_id)
    if b.anchor < 0:
        raise HTTPException(400, "Anchor < 0")
    con = db.connect()
    try:
        r = con.execute("SELECT username, suggestion_status, package_id FROM comments WHERE id=? AND doc_id=? AND parent_id IS NULL",
                        (cid, doc_id)).fetchone()
        if not r:
            raise HTTPException(404, "Comment gone")
        _need_package(con, doc_id, r["package_id"], user)
        if r["username"] != user and not (b.anchor_range and not r["package_id"] and role in ("owner", "editor")):
            raise HTTPException(403, "Only author")
        if r["suggestion_status"] == "pending":
            raise HTTPException(400, "Use accept/reject for suggestions")
        if b.anchor_range:
            con.execute("UPDATE comments SET anchor=?,anchor_range=? WHERE id=? AND anchor_range IS ?",
                        (max(1, b.anchor), b.anchor_range, cid, b.previous_range))
        else:
            con.execute("UPDATE comments SET anchor=? WHERE id=?", (max(1, b.anchor), cid))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@router.post("/api/docs/{doc_id}/comments/{cid}/edit")
def edit_comment(doc_id: str, cid: str, b: CommentEdit, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "comments")
    deps.need_access(user, doc_id)
    if not b.text.strip() or len(b.text.strip()) > 2000:
        raise HTTPException(400, "Comment: 1-2000 chars")
    con = db.connect()
    try:
        r = con.execute("SELECT username, package_id FROM comments WHERE id=? AND doc_id=?",
                        (cid, doc_id)).fetchone()
        if not r:
            raise HTTPException(404, "Comment gone")
        _need_package(con, doc_id, r["package_id"], user)
        if r["username"] != user:
            raise HTTPException(403, "Only author")
        before = con.execute("SELECT text FROM comments WHERE id=?", (cid,)).fetchone()["text"]
        con.execute("UPDATE comments SET text=? WHERE id=?", (b.text.strip(), cid))
        con.commit()
    finally:
        con.close()
    notifications.notify_mentions(doc_id, user, b.text, cid, before)
    emit_doc(doc_id, "comment", exclude=user)
    return {"ok": True}


@router.post("/api/docs/{doc_id}/comments/{cid}/resolve")
def resolve_comment(doc_id: str, cid: str, b: ResolveSet, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "comments")
    role = deps.need_access(user, doc_id)
    con = db.connect()
    try:
        r = con.execute("SELECT username, parent_id, package_id FROM comments WHERE id=? AND doc_id=?",
                        (cid, doc_id)).fetchone()
        if not r:
            raise HTTPException(404, "Comment gone")
        _need_package(con, doc_id, r["package_id"], user)
        top = cid if not r["parent_id"] else r["parent_id"]
        a = con.execute("SELECT username,suggestion_status FROM comments WHERE id=?", (top,)).fetchone()
        if role != "owner" and (not a or a["username"] != user):
            raise HTTPException(403, "Only author or owner")
        if a and a["suggestion_status"]:
            raise HTTPException(400, "Use accept/reject for suggestions")
        con.execute("UPDATE comments SET resolved=? WHERE id=?", (1 if b.resolved else 0, top))
        con.commit()
        emit_doc(doc_id, "comment", exclude=user)
        return {"ok": True}
    finally:
        con.close()
