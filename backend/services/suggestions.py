"""Review suggestions: creating one never edits the document."""
from __future__ import annotations

import logging
import sqlite3
import time

from fastapi import HTTPException
from pycrdt import Doc, Text

from backend import db, deps, sync
from backend.constants import MAX_TXT
from backend.schemas import SuggestionNew
from backend.services import quota

log = logging.getLogger("typst.main")

# Reviewer batches charge the DOC OWNER's quota, so bound what one reviewer
# can park on a single document: at most MAX_PENDING_PER_DOC pending
# suggestions or MAX_PENDING_BYTES_PER_DOC bytes of payload (quota counts
# suggestion_old + replacement per doc) - else the owner pays up to ~ dozens
# of MB per reviewer. create_batch returns a clean 413 once the cap is hit.
MAX_PENDING_PER_DOC = 200
MAX_PENDING_BYTES_PER_DOC = 512 * 1024


def create(user: str, doc_id: str, change: SuggestionNew, author: str = "") -> dict:
    return create_batch(user, doc_id, [change], author)[0]


def create_batch(user: str, doc_id: str, changes: list[SuggestionNew], author: str = "") -> list[dict]:
    deps.need_access(user, doc_id)
    room = sync.room(doc_id)
    results = []
    with sync._doc_lock(room):
        current = str(room["doc"].get("typst", type=Text))
        spans: list[tuple[int, int]] = []
        for change in changes:
            if change.old_string == change.new_string:
                raise HTTPException(400, "Suggestion must change the text")
            if current.count(change.old_string) != 1:
                raise HTTPException(409, "Original text must occur exactly once; include more context")
            at = current.index(change.old_string)
            if any(at < end and at + len(change.old_string) > start for start, end in spans):
                raise HTTPException(400, "Suggestions overlap; combine them")
            spans.append((at, at + len(change.old_string)))
        with db.tx() as con:
            if not db.role_on(con, user, doc_id):
                raise HTTPException(404, "Document not found")
            row = con.execute("SELECT owner,trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
            if row["trashed"]:
                raise HTTPException(410, "In trash - restore first")
            extra = sum(len(c.old_string.encode("utf-8")) + len(c.new_string.encode("utf-8")) for c in changes)
            pending = con.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(CAST(suggestion_old AS BLOB)) "
                "+ LENGTH(CAST(replacement AS BLOB))),0) AS b FROM comments "
                "WHERE doc_id=? AND suggestion_status='pending'", (doc_id,)).fetchone()
            if pending["n"] + len(changes) > MAX_PENDING_PER_DOC or pending["b"] + extra > MAX_PENDING_BYTES_PER_DOC:
                raise HTTPException(413, "Too many pending suggestions on this document")
            quota.check_quota(row["owner"], extra, con)
            for change, (at, _) in zip(changes, spans, strict=True):
                cid = db.new_id("c_")
                anchor = current[:at].count("\n") + 1
                con.execute("INSERT INTO comments (id,doc_id,username,author,anchor,quote,text,created_at,"
                            "suggestion_old,replacement,suggestion_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (cid, doc_id, user, author[:40], anchor, change.old_string[:500], change.text.strip(),
                             db.now_iso(), change.old_string, change.new_string, "pending"))
                results.append({"id": cid, "status": "pending", "anchor": anchor})
    quota.invalidate_quota_cache(row["owner"])
    return results


def accept(user: str, doc_id: str, cid: str) -> tuple[dict, bytes]:
    deps.need_access(user, doc_id)
    room = sync.room(doc_id)
    # Clone first: a failed quota/permission/anchor check cannot change live Yjs state.
    with sync._doc_lock(room):
        live = room["doc"]
        trial: Doc = Doc()
        trial.apply_update(live.get_update())
        text = trial.get("typst", type=Text)
        current = str(text)
        with db.tx() as con:
            role = db.role_on(con, user, doc_id)
            if not role:
                raise HTTPException(404, "Document not found")
            if role not in ("owner", "editor"):
                raise HTTPException(403, "Only an editor or owner may accept suggestions")
            row = con.execute("SELECT owner,content,yjs,trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
            if row["trashed"]:
                raise HTTPException(410, "In trash - restore first")
            change = con.execute("SELECT * FROM comments WHERE id=? AND doc_id=? AND suggestion_status='pending'",
                                 (cid, doc_id)).fetchone()
            if not change:
                raise HTTPException(409, "Suggestion is no longer pending")
            old, new = change["suggestion_old"], change["replacement"]
            if current.count(old) != 1:
                raise HTTPException(409, "Original text changed or is ambiguous; request a new suggestion")
            at = current.index(old)
            content = current[:at] + new + current[at + len(old):]
            if len(content.encode("utf-8")) > MAX_TXT:
                raise HTTPException(400, "Document too large")
            # pycrdt Text indices are UTF-8 byte offsets.
            start = len(current[:at].encode("utf-8"))
            with trial.transaction():
                del text[start:start + len(old.encode("utf-8"))]
                text.insert(start, new)
            update = trial.get_update()
            extra = len(content.encode("utf-8")) + len(update) - len(row["content"].encode("utf-8")) - len(row["yjs"] or b'')
            quota.check_quota(row["owner"], extra, con)
            con.execute("UPDATE docs SET content=?,yjs=?,updated_at=? WHERE id=?", (content, update, db.now_iso(), doc_id))
            # Refresh the quote to the accepted text: the old quote no longer
            # exists once accepted, and stale half-matches would feed the
            # re-anchoring.
            con.execute("UPDATE comments SET suggestion_status='accepted',resolved=1,quote=? WHERE id=?",
                        (new[:500], cid))
        # Snapshot of the pre-accept state: after the commit so a failed
        # accept leaves no stray snapshot; failures only warn.
        try:
            from backend.services import snapshots as snapsvc
            snapsvc.auto_snap(doc_id, current, label="suggestion-accept")
        except (HTTPException, sqlite3.Error, OSError) as e:
            log.warning("suggestion accept snap: %s", e)
        live.apply_update(update)
        room["text_len"] = len(content.encode("utf-8"))
        room["dirty"] = False
        sync._mark_quota_blocked(room, False)
        room["dirty_since"] = 0.0
        room["saved"] = time.monotonic()
    quota.invalidate_quota_cache(row["owner"])
    return room, update


def reject(user: str, doc_id: str, cid: str) -> dict:
    deps.need_access(user, doc_id)
    with db.tx() as con:
        role = db.role_on(con, user, doc_id)
        if not role:
            raise HTTPException(404, "Document not found")
        if role not in ("owner", "editor"):
            raise HTTPException(403, "Only an editor or owner may reject suggestions")
        if con.execute("SELECT trashed FROM docs WHERE id=?", (doc_id,)).fetchone()["trashed"]:
            raise HTTPException(410, "In trash - restore first")
        changed = con.execute("UPDATE comments SET suggestion_status='rejected',resolved=1 "
                              "WHERE id=? AND doc_id=? AND suggestion_status='pending'", (cid, doc_id)).rowcount
        if not changed:
            raise HTTPException(409, "Suggestion is no longer pending")
    return {"ok": True}
