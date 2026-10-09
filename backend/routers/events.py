"""Server-sent events for the sidebar."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend import auth, deps
from backend.services.sidebar import _SIDEBAR_Q

router = APIRouter()


@router.get("/api/events")
async def sidebar_events(req: Request, user: str = Depends(deps.me)):
    deps.limited(req, "files_list")  # like other list reads; churn-reconnects still count
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
                    yield f"event: {msg}\ndata: 1\n\n"
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
