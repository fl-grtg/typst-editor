"""MCP server: FastMCP typst-editor + 8 tools (M2: 7, M3: view).

Mounted in backend/main.py: app.mount("/mcp", _mcp_app).
Auth per request: Authorization Bearer API key only (no cookie fallback,
so the /mcp CSRF bypass carries no ambient auth). Every call counts
against RATE_MCP_PER_MIN. HTTPException from mcp_tools becomes ToolError.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from backend import mcp_tools as t

log = logging.getLogger("typst.mcp")

mcp = FastMCP("typst-editor")


def _auth() -> tuple[str, str, str]:
    """(user, cap, author) from Bearer API key. Raises ToolError 401/429.

    Bearer-only on purpose: no cookie fallback, so the /mcp CSRF bypass
    carries no ambient auth. author is the key name (comment display),
    else the username. Every call counts against RATE_MCP_PER_MIN
    (IP + per-key buckets, same helper as the REST routes)."""
    from fastmcp.server.dependencies import get_http_headers, get_http_request

    from backend import main as _main

    h = get_http_headers(include={"authorization"})
    authz = h.get("authorization", "")
    if not authz.lower().startswith("bearer "):
        raise ToolError("401: Bearer API key required")
    hit = _main.verify_api_key(authz[7:].strip())
    if not hit:
        raise ToolError("401: Invalid API key")
    user, cap = hit["user"], hit["role"]
    author = (hit.get("key_name") or "").strip() or user
    try:
        _main.limited(get_http_request(), "mcp", f"{user}:{hit['id']}")
    except RuntimeError:
        log.warning("mcp auth without request context, skipping rate limit")
    except HTTPException as e:
        raise ToolError(f"{e.status_code}: {e.detail}") from None
    return user, cap, author


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except HTTPException as e:
        raise ToolError(f"{e.status_code}: {e.detail}") from None


async def _awrap(coro):
    try:
        return await coro
    except HTTPException as e:
        raise ToolError(f"{e.status_code}: {e.detail}") from None


@mcp.tool()
def ls(path: str = "/") -> dict:
    """List docs/shared/templates, or files inside a document. Start here."""
    user, cap, _ = _auth()
    return _wrap(t.op_ls, user, cap, path)


@mcp.tool()
def read(path: str, offset: int = 1, limit: int = 0) -> dict:
    """Read a doc, text file or template. Line window: offset 1-based, limit 0 = all. Returns content + total_lines + last_seen (pass it to edit)."""
    user, cap, _ = _auth()
    return _wrap(t.op_read, user, cap, path, offset, limit)


@mcp.tool()
def create(path: str, content: str = "") -> dict:
    """Create a doc (/docs/{Title}), text file (/docs/{Title}/{File}) or template. 400 if it exists."""
    user, cap, _ = _auth()
    return _wrap(t.op_create, user, cap, path, content)


@mcp.tool()
async def edit(path: str, old_string: str, new_string: str,
               replace_all: bool = False, last_seen: str | None = None) -> dict:
    """Anchor edit: old_string (2-3 lines context) must match exactly once, or use
    replace_all=true. 0x -> 409 anchor-gone, >1x -> 409 anchor-ambiguous."""
    user, cap, _ = _auth()
    return await _awrap(t.op_edit(user, cap, path, old_string, new_string, replace_all, last_seen))


@mcp.tool()
def search(query: str) -> dict:
    """Search titles + content of accessible docs (min 2 chars, max 20 hits)."""
    user, cap, _ = _auth()
    return _wrap(t.op_search, user, cap, query)


@mcp.tool()
def upload(path: str, content_base64: str, filename: str | None = None) -> dict:
    """Upload/replace an attachment: /docs/{Title}/{File} or /docs/{Title} + filename. Max 10 MB."""
    user, cap, _ = _auth()
    return _wrap(t.op_upload, user, cap, path, content_base64, filename)


@mcp.tool()
def comment(path: str, anchor: int, text: str, quote: str = "",
            parent_id: str | None = None) -> dict:
    """Comment on a document (any role with read access, incl. reviewer)."""
    user, cap, author = _auth()
    return _wrap(t.op_comment, user, cap, path, anchor, text, quote, parent_id, author)


@mcp.tool()
async def view(path: str, pages: str = "1-5") -> dict:
    """Render doc pages 1-5 as PNG (base64, width <=1024px). Fix code, then re-view."""
    user, cap, _ = _auth()
    return await _awrap(t.op_view(user, cap, path, pages))


# Single instance: main mounts exactly this object and runs its lifespan
# inside the parent lifespan (mounted sub-app lifespans don't run alone).
mcp_http_app = mcp.http_app(path="/", stateless_http=True)
