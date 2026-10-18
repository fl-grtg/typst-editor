"""MCP server: FastMCP typst-editor with document, review, render and export tools.

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
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations

from backend import mcp_tools as t
from backend.routers.change_packages import ProposalFile

log = logging.getLogger("typst.mcp")

mcp = FastMCP("typst-editor")


def _auth() -> tuple[str, str, str]:
    """(user, cap, author) from Bearer API key. Raises ToolError 401/429.

    Bearer-only on purpose: no cookie fallback, so the /mcp CSRF bypass
    carries no ambient auth. author is the key name (comment/proposal display),
    else the username. Every call counts against RATE_MCP_PER_MIN
    (IP + per-key buckets, same helper as the REST routes)."""
    from fastmcp.server.dependencies import get_http_headers, get_http_request

    from backend import deps
    from backend.services import apikeys

    h = get_http_headers(include={"authorization"})
    authz = h.get("authorization", "")
    if not authz.lower().startswith("bearer "):
        raise ToolError("401: Bearer API key required")
    hit = apikeys.verify_api_key(authz[7:].strip())
    if not hit:
        raise ToolError("401: Invalid API key")
    user, cap = hit["user"], hit["role"]
    author = (hit.get("key_name") or "").strip() or user
    try:
        deps.limited(get_http_request(), "mcp", f"{user}:{hit['id']}")
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


@mcp.tool(
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
def ls(path: str = "/") -> dict:
    """List docs/shared/templates/projects, or files inside a document. Start here."""
    user, cap, _ = _auth()
    return _wrap(t.op_ls, user, cap, path)


@mcp.tool(
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
def read(path: str, offset: int = 1, limit: int = 0, binary: bool = False) -> dict:
    """Read a doc, text file, template or project resource. Line window: offset 1-based, limit 0 = all. Returns content + total_lines + last_seen (pass it to edit). binary=true reads attachment bytes as content_base64 (max 10 MB), usable as the base for binary proposals."""
    user, cap, _ = _auth()
    return _wrap(t.op_read, user, cap, path, offset, limit, binary)


@mcp.tool()
def create(path: str, content: str = "") -> dict:
    """Create a doc (/docs/{Title}), text file (/docs/{Title}/{File}), template or project doc/resource. 400 if it exists (409 for project collisions)."""
    user, cap, _ = _auth()
    return _wrap(t.op_create, user, cap, path, content)


@mcp.tool()
async def edit(path: str, old_string: str, new_string: str,
               replace_all: bool = False, last_seen: str | None = None) -> dict:
    """Anchor edit: old_string (2-3 lines context) must match exactly once, or use
    replace_all=true. 0x -> 409 anchor-gone, >1x -> 409 anchor-ambiguous."""
    user, cap, _ = _auth()
    return await _awrap(t.op_edit(user, cap, path, old_string, new_string, replace_all, last_seen))


@mcp.tool(
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
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
def suggest(path: str, old_string: str, new_string: str, text: str = "") -> dict:
    """Submit one document text change as a normal project proposal package.
    old_string must match exactly once (empty only for an empty document).
    text names the package (max 100 chars). For multiple files, uploads, additions, deletions or
    renames use propose instead. Source stays unchanged until UI acceptance."""
    user, cap, author = _auth()
    return _wrap(t.op_suggest_package, user, cap, path, old_string, new_string, text, author)


@mcp.tool(
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
def suggestions(path: str) -> dict:
    """List normal proposal packages for a project or its document. Use proposals with package_id to read full changes and revision."""
    user, cap, _ = _auth()
    return _wrap(t.op_proposals, user, cap, path)


@mcp.tool()
def propose(path: str, title: str, files: list[ProposalFile], package_id: str = "", revision: int = 0) -> dict:
    """Submit/correct a normal UI proposal package without changing source.
    path: /projects/{id}. files use the same schema as human packages:
    kind document/resource/file; doc_id from ls for documents/attachments;
    path main.typ for documents, otherwise relative filename;
    action modify/add/delete/rename; base original text or null for add;
    content proposed text (omit for delete); target for rename;
    binary=true means base/content are base64 attachment bytes.
    For document add omit doc_id and set target to its title; document rename
    uses target as new title and original_title for conflict detection.
    Text modify needs changes=[{old_string,new_string}] matching base/content.
    Include reference edits alongside renames/deletions. No automatic rewrite.
    To correct a package read it first, retain file/change ids, and pass its
    package_id and revision. Owner/editor reviews and accepts in the existing
    proposal mode, by change, file or whole package. Reviewer keys work."""
    user, cap, author = _auth()
    return _wrap(t.op_propose, user, cap, path, title,
                 [f.model_dump(exclude_defaults=True) for f in files], package_id, revision, author)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
def proposals(path: str, package_id: str = "") -> dict:
    """List project proposal packages, or read one including base/content, file/change ids and revision for correction. path is /projects/{id} or a document in that project. Project membership required."""
    user, cap, _ = _auth()
    return _wrap(t.op_proposals, user, cap, path, package_id)


@mcp.tool(
    output_schema={
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "total_pages": {"type": "integer"},
            "cache_hit": {"type": "boolean"},
            "last_seen": {"type": "string"},
            "pages": {"type": "string"},
            "scale": {"type": "number"},
        },
        "required": ["count", "total_pages", "cache_hit", "last_seen"],
        "additionalProperties": False,
    },
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def view(path: str, pages: str = "1-5", scale: float = 1.0) -> ToolResult:
    """Render doc pages 1-20 as viewable image blocks (no manual decode needed). Pages format: "2", "1-5", "6-10", "1-3,5" (max 20 per call); scale 0.5-3.0 (default 1.0, ppi 144*scale). Returns image blocks + count/total_pages/cache_hit/last_seen. Fix code, then re-view."""
    user, cap, _ = _auth()
    return await _awrap(t.op_view(user, cap, path, pages, scale))


@mcp.tool(
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
async def export(path: str, format: str = "pdf", pdf_standard: str = "none", pages: str = "", ppi: int = 0) -> dict:
    """Export a document via typst CLI (REST POST /api/docs/{id}/export parity). format pdf = full PDF; svg/png = single page directly, multi-page docs as ZIP of pages; zip = source bundle (main.typ + sources at their original relative paths). Options: pdf_standard (pdf only), pages like 1-3,5 (pdf/svg/png), ppi 72-300 (png only). Returns base64 payload + mime + filename (decode and save)."""
    user, cap, _ = _auth()
    return await _awrap(t.op_export(user, cap, path, format, pdf_standard, pages, ppi))


# Single instance: main mounts exactly this object and runs its lifespan
# inside the parent lifespan (mounted sub-app lifespans don't run alone).
mcp_http_app = mcp.http_app(path="/", stateless_http=True)
