"""MCP server: the agent's view of the editor, 13 tools over one path grammar.

Mounted in backend/main.py: app.mount("/mcp", _mcp_app).
Auth per request: Authorization Bearer API key only (no cookie fallback, so the /mcp CSRF
bypass carries no ambient auth). Every call counts against RATE_MCP_PER_MIN and is logged
to agent_log. Failures reach the agent as JSON {code, message, hint, ...}.
"""
from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import HTTPException
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from fastmcp.utilities.types import Image
from mcp.types import Annotations, ToolAnnotations
from pydantic import BaseModel, Field

from backend import db, mcp_render, mcp_review
from backend import mcp_fs as fs

log = logging.getLogger("typst.mcp")

INSTRUCTIONS = """Typst documents in projects. A path is /{Project}/{folder}/{Document}; a document IS its title.
Attachments live under their document (/P/Doc/img/a.png), shared modules under /P/.library/, proposals under /P/.proposals/,
private templates under /.templates/, deleted things under /.trash/. Foreign projects are "Title@owner". Start with ls.
Work: ls -> read(outline=true) -> edit/write -> render (errors) -> render(pages=...) to look -> export.
Pass base_version (from read) when overwriting. Send related changes as ONE package: in shared projects and for reviewer keys
edit/write/move/delete become proposals; reuse package=<id> to add to it. Humans accept single hunks. You may delete your own
proposals and comments. Large files: upload / export give one-time curl links. inbox shows mentions and review results."""

mcp = FastMCP("typst-editor", instructions=INSTRUCTIONS)

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True)


class Edit(BaseModel):
    old: str = Field(description="Exact text to replace; quote 2-3 lines so it matches once")
    new: str
    all: bool = Field(False, description="Replace every match (renames)")


class Op(BaseModel):
    op: Literal["write", "edit", "move", "delete"]
    path: str
    content: str | None = None
    content_base64: str = ""
    edits: list[Edit] = []
    to: str = ""


def _code(status: int) -> str:
    return {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict", 410: "gone", 413: "too_large",
            422: "compile_error", 429: "rate_limited", 503: "busy"}.get(status, "error")


def _fail(e: HTTPException) -> ToolError:
    d: dict = dict(e.detail) if isinstance(e.detail, dict) else {"message": str(e.detail)}
    d.setdefault("code", _code(e.status_code))
    if retry := (e.headers or {}).get("Retry-After"):
        d["retry_after"] = int(retry)
    elif e.status_code == 429:
        d["retry_after"] = 60
        d.setdefault("hint", "wait and retry once; the limit is per minute")
    return ToolError(json.dumps(d, ensure_ascii=False))


def _auth() -> tuple[fs.Ctx, str, str]:
    """(ctx, key id, public base url) from the Bearer key; 401/429 as tool errors."""
    from fastmcp.server.dependencies import get_http_headers, get_http_request

    from backend import deps
    from backend.services import apikeys
    from backend.services.proxy import _proxy_trusted

    authz = get_http_headers(include={"authorization"}).get("authorization", "")
    if not authz.lower().startswith("bearer "):
        raise _fail(HTTPException(401, "Bearer API key required"))
    hit = apikeys.verify_api_key(authz[7:].strip())
    if not hit:
        raise _fail(HTTPException(401, "Invalid API key"))
    req = get_http_request()
    try:
        deps.limited(req, "mcp", f"{hit['user']}:{hit['id']}")
    except HTTPException as e:
        raise _fail(e) from None
    scheme = req.url.scheme
    if _proxy_trusted(req) and req.headers.get("x-forwarded-proto"):
        scheme = req.headers["x-forwarded-proto"].split(",")[-1].strip()
    base = f"{scheme}://{req.headers.get('host', req.url.netloc)}"
    ctx = fs.Ctx(user=hit["user"], cap=hit["role"], author=(hit.get("key_name") or "").strip() or hit["user"], mode=hit.get("mode", "auto"))
    return ctx, hit["id"], base


def _log(key_id: str, tool: str, path: str, ok: bool) -> None:
    try:
        con = db.connect()
        try:
            con.execute("INSERT INTO agent_log (key_id,tool,path,ok,at) VALUES (?,?,?,?,?)", (key_id, tool, path[:300], int(ok), db.now_iso()))
            con.execute("DELETE FROM agent_log WHERE key_id=? AND id NOT IN (SELECT id FROM agent_log WHERE key_id=? ORDER BY id DESC LIMIT 500)", (key_id, key_id))
            con.commit()
        finally:
            con.close()
    except Exception as e:
        log.warning("agent log failed: %s", e)


async def _run(tool: str, path: str, call):
    ctx, key_id, base = _auth()
    try:
        out = call(ctx, base)
        out = await out if hasattr(out, "__await__") else out
    except HTTPException as e:
        _log(key_id, tool, path, False)
        raise _fail(e) from None
    _log(key_id, tool, path, True)
    return out


@mcp.tool(annotations=READ_ONLY)
async def ls(path: str = "/", depth: int = 1, versions: bool = False) -> dict:
    """List a path. / = projects; a project or folder = its documents, folders, attachments, modules, proposals (depth 0 = everything below). A document shows its version and, with versions=true, saved snapshots."""
    return await _run("ls", path, lambda c, b: fs.ls(c, path, depth, versions))


@mcp.tool(annotations=READ_ONLY, output_schema=None)
async def read(path: str, offset: int = 1, limit: int = 0, outline: bool = False, version: str = "") -> ToolResult | dict:
    """Read a document, text attachment, module, template or proposal. Returns content, version (pass it as base_version when writing), total_lines and for documents the open comments (id, line, quote, text). outline=true adds headings, labels, #let names and imports with what they resolve to. version=<snapshot id> reads an older document version. Images come back as images."""
    out, image = await _run("read", path, lambda c, b: fs.read(c, path, offset, limit, outline, version))
    if image is None:
        return out
    fmt = path.rsplit(".", 1)[-1].lower().replace("jpg", "jpeg")
    return ToolResult(content=[json.dumps(out), Image(data=image, format=fmt, annotations=Annotations(audience=["assistant"]))], structured_content=out)


@mcp.tool()
async def write(path: str, content: str | None = None, content_base64: str = "", copy_from: str = "", base_version: str = "",
                force: bool = False, package: str = "") -> dict:
    """Create or overwrite. /Project = new project; /P/Folder/ = folder; /P/Folder/Name = document; /P/Doc/file.png = attachment (content_base64 for binaries); /P/.library/x.typ = module; /.templates/x.typ = template. copy_from=<path> copies server-side (also across projects). Overwriting needs base_version from read (or force=true). In shared projects this becomes a proposal."""
    return await _run("write", path, lambda c, b: fs.write(c, path, content, content_base64, copy_from, base_version, force, package))


@mcp.tool()
async def edit(path: str, edits: list[Edit], base_version: str = "", package: str = "") -> dict:
    """Exact-text edits on a document, text attachment, module or template, all applied atomically against the text as it is now. old must match once (2-3 lines of context) or set all=true. Errors list the matches or the closest line. Edits keep concurrent typing of people in the open editor."""
    return await _run("edit", path, lambda c, b: fs.edit(c, path, [e.model_dump() for e in edits], base_version, package))


@mcp.tool()
async def move(path: str, to: str, fix_refs: bool = True, package: str = "") -> dict:
    """Rename or move inside one project: a document (new title and/or folder), an attachment (inside its document), a module, a folder (end both paths with /), a project (/NewTitle), a template, or restore /.trash/<id> (to="/"; it returns to its original place). Quoted references to a moved file or module are rewritten when fix_refs is true."""
    return await _run("move", path, lambda c, b: fs.move(c, path, to, fix_refs, package))


@mcp.tool()
async def delete(path: str, package: str = "") -> dict:
    """Delete to the trash (recoverable under /.trash): document, attachment, module, template, project, empty folder (path ends with /), or one of your own proposals (/P/.proposals/<id>). Comments are deleted with the comment tool."""
    return await _run("delete", path, lambda c, b: fs.delete(c, path, package))


@mcp.tool(annotations=READ_ONLY)
async def search(query: str, path: str = "/", kind: str = "") -> dict:
    """Search titles and text of documents, attachments, modules, templates and the trash you can see. Hits carry path, kind, line, snippet and match count. path limits to a project or folder, kind to doc|file|module|template|trash."""
    return await _run("search", path, lambda c, b: fs.find(c, query, path, kind))


@mcp.tool(annotations=READ_ONLY, output_schema=None)
async def render(path: str, pages: str = "", scale: float = 1.0) -> ToolResult | dict:
    """Compile a document. Without pages: only the check (ok, page count, warnings; errors list file, line, col, message). With pages ("2", "1-5", "1-3,5"; max 20) you also get page images; scale 0.5-3. Render after changes and fix errors before looking."""
    return await _run("render", path, lambda c, b: mcp_render.render_doc(c, path, pages, scale))


@mcp.tool(annotations=READ_ONLY)
async def export(path: str, format: str = "pdf", pdf_standard: str = "none", pages: str = "", ppi: int = 0) -> dict:
    """Export a document as pdf, svg, png (several pages arrive as a zip) or zip (sources), or fetch any file/module/template. ppi 72-300 for png. Returns a download url valid for 5 minutes (curl it) and, when small, content_base64."""
    return await _run("export", path, lambda c, b: mcp_render.export(c, path, b, format, pdf_standard, pages, ppi))


@mcp.tool()
async def upload(path: str) -> dict:
    """Get a one-time upload url for a file of up to 10 MB: curl -T <local-file> <url> writes it to path (document, attachment, module or template, new or existing; replaces it). Use this instead of content_base64 for anything big."""
    return await _run("upload", path, lambda c, b: mcp_render.upload(c, path, b))


@mcp.tool()
async def comment(path: str, text: str = "", quote: str = "", line: int = 0, reply_to: str = "", id: str = "",
                  resolved: bool | None = None, delete: bool = False) -> dict:
    """Comment on a document: text plus quote (the marked passage, moves with the text) or line; reply_to=<thread id> answers a thread. With id: resolved=true/false closes or reopens a thread, delete=true removes your own comment. @name mentions people or keys."""
    return await _run("comment", path, lambda c, b: mcp_review.comment(c, path, text, quote, line, reply_to, id, resolved, delete))


@mcp.tool()
async def propose(project: str, ops: list[Op], title: str = "", package: str = "") -> dict:
    """Hand in related changes as ONE proposal package: ops are write, edit, move or delete on paths of that project (same arguments as the tools). The server works out the hunks; humans accept single hunks, files or all. Use package=<id> to add to or correct your package; delete it via delete(/P/.proposals/<id>)."""
    async def call(c: fs.Ctx, b: str):
        node = fs.resolve(c, project)
        if node["kind"] != "project":
            raise fs.err(400, "bad_path", "project must be a project path like /Report")
        internal: list[dict] = []
        for o in ops:
            if o.op == "write":
                data, as_text = fs.source(c, o.content, o.content_base64, "")
                internal.append({"op": "write", "path": o.path, "data": data, "text": as_text})
            elif o.op == "edit":
                internal.append({"op": "edit", "path": o.path, "edits": [e.model_dump() for e in o.edits]})
            elif o.op == "move":
                internal += fs.move_ops(c, o.path, o.to)
            else:
                internal.append({"op": "delete", "path": o.path})
        return await mcp_review.propose(c, node["project_id"], internal, title, package)

    return await _run("propose", project, call)


@mcp.tool(annotations=READ_ONLY)
async def inbox(since: str = "", wait: float = 0, ack: list[str] | None = None) -> dict:
    """Unread mentions of @<your key name> and results of your proposals (accepted, partly accepted, discarded). wait=<seconds, max 25> holds the call until something arrives; ack=[ids] marks items handled; since=<value from the last call> only returns newer ones."""
    return await _run("inbox", "", lambda c, b: mcp_review.inbox(c, since, wait, ack))


# Single instance: main mounts exactly this object and runs its lifespan
# inside the parent lifespan (mounted sub-app lifespans don't run alone).
mcp_http_app = mcp.http_app(path="/", stateless_http=True)
