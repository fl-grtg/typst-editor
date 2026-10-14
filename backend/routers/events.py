"""Server-sent events: sidebar refresh + typed per-user/per-doc channel.

Same transport as before (no new connection): queue items are "sidebar"
or "<type>:<doc_id>" (see services/sidebar.py). ?doc_id= filters the
stream to one document; without it the client gets everything.
Body stays "event: <type>\\ndata: <doc_id|1>".
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend import auth, deps
from backend.services.sidebar import _SIDEBAR_Q

router = APIRouter()


def split_event(item: str) -> tuple[str, str]:
    """'file:d_1' -> ('file', 'd_1'); 'sidebar' -> ('sidebar', '')."""
    if ":" in item:
        etype, data = item.split(":", 1)
        return (etype or "sidebar", data)
    return (item or "sidebar", "")


def match_event(item: str, doc_filter: str) -> bool:
    """Per-doc stream only gets events for that doc; the unfiltered
    stream gets everything."""
    if not doc_filter:
        return True
    etype, data = split_event(item)
    if etype == "sidebar" or not data:
        return False
    return data == doc_filter


@router.get("/api/events")
async def sidebar_events(req: Request, user: str = Depends(deps.me), doc_id: str = ""):
    deps.limited(req, "files_list")  # like other list reads; churn-reconnects still count
    if doc_id:
        deps.check_doc_id(doc_id)
        deps.need_access(user, doc_id)
    if len(_SIDEBAR_Q.get(user, ())) >= 5:
        raise HTTPException(429, "Too many streams")
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    entry = (loop, q)
    _SIDEBAR_Q.setdefault(user, set()).add(entry)

    async def _gen():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                    if not match_event(msg, doc_id):
                        continue
                    etype, data = split_event(msg)
                    yield f"event: {etype}\ndata: {data or '1'}\n\n"
                except TimeoutError:
                    if not auth.verify_session(req.cookies.get(deps.COOKIE, "")):
                        break  # logged out/expired/revoked mid-stream: stop, client reconnects on next login
                    yield ": ping\n\n"  # keep proxies from closing idle streams
        finally:
            _left = _SIDEBAR_Q.get(user, set())
            _left.discard(entry)
            if not _left:
                _SIDEBAR_Q.pop(user, None)

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
