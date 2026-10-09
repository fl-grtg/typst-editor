"""WebSocket endpoint for live document sync."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket

from backend import deps, sync

router = APIRouter()


@router.websocket("/ws/{doc_id}")
async def ws_doc(ws: WebSocket, doc_id: str) -> None:
    try:
        deps.check_doc_id(doc_id)
    except HTTPException:
        await ws.accept()
        await ws.close(code=4403)
        return
    await sync.handle(ws, doc_id)
