"""Short-lived upload and download links for agents: big files stay out of the model's context.

A link is a random token held in memory; it carries the identity and rights of the key that asked.
Downloads hold the already rendered bytes, uploads are one-shot writes to a path.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Request, Response

from backend import deps
from backend.constants import UPLOAD_MAX
from backend.mcp_fs import Ctx

router = APIRouter()

TTL = 300.0
MAX_LINKS = 50
MAX_BYTES = 150 * 1024 * 1024


@dataclass
class Link:
    ctx: Ctx
    expires: float
    path: str = ""  # upload target
    name: str = ""  # download file name
    mime: str = ""
    data: bytes = b""


_links: dict[str, Link] = {}


def _sweep() -> None:
    now = time.monotonic()
    for t in [t for t, lk in _links.items() if lk.expires < now]:
        _links.pop(t)


def _add(link: Link) -> str:
    _sweep()
    if len(_links) >= MAX_LINKS or sum(len(lk.data) for lk in _links.values()) + len(link.data) > MAX_BYTES:
        raise HTTPException(429, {"code": "busy", "message": "Too many open transfer links; use them or wait a few minutes"})
    token = secrets.token_urlsafe(24)
    _links[token] = link
    return token


def offer_download(ctx: Ctx, name: str, mime: str, data: bytes) -> str:
    return _add(Link(ctx, time.monotonic() + TTL, name=name, mime=mime, data=data))


def offer_upload(ctx: Ctx, path: str) -> str:
    return _add(Link(ctx, time.monotonic() + TTL, path=path))


@router.get("/api/transfer/{token}")
def download(token: str, req: Request) -> Response:
    deps.limited(req, "file_read")
    _sweep()
    link = _links.get(token)
    if not link or not link.name:
        raise HTTPException(404, "Link expired or unknown")
    return Response(link.data, media_type=link.mime or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{link.name}"', "X-Content-Type-Options": "nosniff",
                             "Cache-Control": "no-store"})


@router.put("/api/transfer/{token}")
async def upload(token: str, req: Request) -> dict:
    from backend import mcp_fs

    deps.limited(req, "files")
    _sweep()
    link = _links.get(token)
    if not link or not link.path:
        raise HTTPException(404, "Link expired or unknown")
    body = await deps.read_capped_body(req, UPLOAD_MAX)
    _links.pop(token, None)
    import base64

    return await mcp_fs.write(link.ctx, link.path, content_base64=base64.b64encode(body).decode(), force=True)
