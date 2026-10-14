"""Version snapshot routes."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request

from backend import db, deps, sync
from backend.schemas import SnapNew, SnapRestore
from backend.services.snapshots import prune_snaps

router = APIRouter()


@router.get("/api/docs/{doc_id}/snapshots")
def list_snaps(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    con = db.connect()
    try:
        rows = con.execute("SELECT id, label, created_at, LENGTH(content) AS size FROM snapshots "
                           "WHERE doc_id=? ORDER BY created_at DESC, rowid DESC", (doc_id,)).fetchall()
        return {"snapshots": [dict(r) for r in rows]}
    finally:
        con.close()


@router.post("/api/docs/{doc_id}/snapshots")
def make_snap(doc_id: str, b: SnapNew, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "snapshots")
    deps.need_edit(user, doc_id)
    live = sync.room_text(doc_id)
    con = db.connect()
    try:
        row = con.execute("SELECT content FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Doc gone")
        cur = live if live is not None else row["content"]
        deps.check_quota(deps._owner(doc_id, user), len(cur.encode("utf-8")))
        sid = db.new_id("s_")
        con.execute("INSERT INTO snapshots (id, doc_id, content, label, created_at) VALUES (?,?,?,?,?)",
                    (sid, doc_id, cur, b.label.strip()[:80], db.now_iso()))
        prune_snaps(con, doc_id)
        con.commit()
        return {"id": sid}
    finally:
        con.close()


@router.get("/api/docs/{doc_id}/snapshots/{sid}")
def get_snap(doc_id: str, sid: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    con = db.connect()
    try:
        r = con.execute("SELECT content, label, created_at FROM snapshots WHERE id=? AND doc_id=?",
                        (sid, doc_id)).fetchone()
        if not r:
            raise HTTPException(404, "Snapshot gone")
        return dict(r)
    finally:
        con.close()


@router.post("/api/docs/{doc_id}/snapshots/{sid}/restore")
async def restore_snap(doc_id: str, sid: str, req: Request, user: str = Depends(deps.me),
                       force: bool = False, b: SnapRestore | None = None) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "snapshots")
    deps.need_edit(user, doc_id)
    eff = force or (b.force if b else False)  # query or body flag, default safe
    auto = sync.room_text(doc_id)
    try:
        with db.tx() as con:
            # B5: outer need_edit is a fast-path only; re-check on the tx
            # connection before restoring (role may change in the gap).
            if deps._tx_role(con, user, doc_id) not in ("owner", "editor"):
                raise HTTPException(403, "Reviewer can only comment")
            s = con.execute("SELECT content FROM snapshots WHERE id=? AND doc_id=?", (sid, doc_id)).fetchone()
            if not s:
                raise HTTPException(404, "Snapshot gone")
            cur = con.execute("SELECT content, trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
            if not cur:
                raise HTTPException(404, "Doc gone")
            if cur["trashed"]:
                raise HTTPException(410, "In trash - restore first")
            if auto is not None and auto != (cur["content"] or "") and not eff:
                raise HTTPException(409, "Document changed meanwhile, retry with force")
            before = auto if auto is not None else cur["content"]
            deps.check_quota(deps._owner(doc_id, user), max(0, len((s["content"] or "").encode("utf-8")) - len((cur["content"] or "").encode("utf-8"))))
            con.execute("INSERT INTO snapshots (id, doc_id, content, label, created_at) VALUES (?,?,?,?,?)",
                        (db.new_id("s_"), doc_id, before, "Before restore", db.now_iso()))
            prune_snaps(con, doc_id)
            con.execute("UPDATE docs SET content=?, updated_at=? WHERE id=?", (s["content"], db.now_iso(), doc_id))
    except sqlite3.OperationalError as e:
        raise deps.busy_503("restore_snap", e) from e
    await sync.replace_text(doc_id, s["content"])
    return {"ok": True}


@router.delete("/api/docs/{doc_id}/snapshots/{sid}")
def delete_snap(doc_id: str, sid: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "snapshots")
    if deps.need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can delete snapshots")
    con = db.connect()
    try:
        con.execute("DELETE FROM snapshots WHERE id=? AND doc_id=?", (sid, doc_id))
        con.commit()
        return {"ok": True}
    finally:
        con.close()
