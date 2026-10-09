"""Per-user event queues over the existing SSE connection (/api/events).

Queue items are strings: "sidebar" (legacy list refresh) or
"<type>:<doc_id>" / "<type>" for typed events. Types: comment, file,
member, notification. Follow-ups: 3D consumes comment/file/member +
notification, 3A the file/member events for tree + tabs.
"""
from __future__ import annotations

import logging

log = logging.getLogger("typst.main")


_SIDEBAR_Q: dict[str, set] = {}  # user -> {(loop, queue)} live /api/events streams (single worker)

EVENT_TYPES = ("sidebar", "comment", "file", "member", "notification")

# Typed events are never coalesced (each one crosses the stream); only the
# idempotent sidebar refresh collapses. Cap guards a stuck consumer.
_TYPED_CAP = 100


def _push(user: str, item: str, coalesce: bool = False) -> None:
    try:
        _targets = list(_SIDEBAR_Q.get(user, ()))
    except RuntimeError:
        log.debug("sidebar race, next mutation retries")
        return  # set mutated concurrently; the next mutation notifies again
    for _loop, _q in _targets:
        try:
            if coalesce and not _q.empty():
                continue
            if _q.qsize() >= _TYPED_CAP:
                log.warning("sidebar queue full for %s, dropping %r", user, item)
                continue
            _loop.call_soon_threadsafe(_q.put_nowait, item)
        except Exception as e:
            log.debug("sidebar push dropped: %s", e)


def notify_sidebar(user: str) -> None:
    # Own list changed elsewhere (MCP, other tab): wake every open sidebar stream of this user.
    # Def endpoints run in a worker thread: schedule into the loop thread-safely.
    # Coalesce: one pending event is enough, sidebar() refetches everything anyway.
    _push(user, "sidebar", coalesce=True)


def emit(user: str, etype: str, doc_id: str = "") -> None:
    """Typed per-user event. Unknown types are dropped (fail-closed)."""
    if etype not in EVENT_TYPES or etype == "sidebar":
        log.warning("sidebar emit dropped bad type: %r", etype)
        return
    _push(user, f"{etype}:{doc_id}" if doc_id else etype)


def doc_users(doc_id: str) -> list[str]:
    """Owner + sharees of a doc (event fan-out, read-only)."""
    from backend import db as _db

    con = _db.connect()
    try:
        d = con.execute("SELECT owner FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not d:
            return []
        rows = con.execute("SELECT username FROM shares WHERE doc_id=?", (doc_id,)).fetchall()
        return [d["owner"], *[r["username"] for r in rows]]
    finally:
        con.close()


def emit_doc(doc_id: str, etype: str, exclude: str = "") -> None:
    """Typed per-doc event to everyone with access (owner + sharees)."""
    for user in doc_users(doc_id):
        if user != exclude:
            emit(user, etype, doc_id)
