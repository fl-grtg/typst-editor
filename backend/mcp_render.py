"""Agent render tools: compile check, page images, exports and transfer links."""
from __future__ import annotations

import asyncio
import base64
import mimetypes

from fastapi import HTTPException

from backend import render
from backend.mcp_fs import Ctx, err, read_bytes, resolve, version
from backend.routers import transfer

INLINE_MAX = 128 * 1024


def _doc(ctx: Ctx, path: str) -> dict:
    node = resolve(ctx, path)
    if node["kind"] != "doc":
        raise err(400, "bad_path", "Only documents can be rendered", hint="name a document path")
    return node


def _label(file: str | None, node: dict) -> str | None:
    """Diagnostics name the document path; other files lose the temp dir in front of them."""
    parts = (file or "").replace("\\", "/").split("/")
    for i, seg in enumerate(parts):
        if seg.startswith(("check-doc-", "export-doc-", "mcp-view-")):
            file = "/".join(parts[i + 1:])
            break
    return node["path"] if file == render.ENTRY else file


def _compile_error(e: HTTPException, node: dict) -> HTTPException:
    """Diagnostics name the document by its path instead of the compile entry file."""
    d: dict = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
    diags = [{**x, "file": _label(x.get("file"), node)} for x in d.get("diagnostics", [])]
    return err(422, "compile_error", _clean(d.get("message", "compile error"), node), diagnostics=diags)


def _clean(text: str, node: dict) -> str:
    """Compiler output without the server's temp directory."""
    out = []
    for word in text.split(" "):
        parts = word.replace("\\", "/").split("/")
        hit = next((i for i, seg in enumerate(parts) if seg.startswith(("check-doc-", "export-doc-", "mcp-view-"))), None)
        out.append("/".join(parts[hit + 1:]) if hit is not None else word)
    return " ".join(out).replace(render.ENTRY, node["path"])


def _source(node: dict):
    return render._collect_export_source(node["doc_id"], max_bytes=render.VIEW_SRC_MAX, skip_oversize=False)


async def render_doc(ctx: Ctx, path: str, pages: str = "", scale: float = 1.0):
    node = _doc(ctx, path)
    main_text, files, _ = await asyncio.to_thread(_source, node)
    try:
        info = await asyncio.to_thread(render.check_source, main_text, files)
        if not pages:
            return {"path": node["path"], "ok": True, **info, "warnings": [{**w, "file": _label(w.get("file"), node)} for w in info["warnings"]]}
        wanted = render._expand_pages(pages)
        if info["pages"] and max(wanted) > info["pages"]:
            raise err(400, "bad_request", f"The document has {info['pages']} page(s); pages {pages!r} is out of range")
        ppi = render._check_scale(scale)
        arg = ",".join(str(p) for p in wanted)
        key = render._view_key(node["doc_id"], main_text, files, arg, ppi)
        hit = render._view_cache_get(key)
        if hit is not None:
            pngs, cached = hit["pngs"], True
        else:
            pngs, cached = await asyncio.to_thread(render._compile_pngs, main_text, files, arg, ppi), False
            render._view_cache_put(key, {"pngs": pngs, "total_pages": None})
        total = await asyncio.to_thread(render._total_pages_exact, node["doc_id"], main_text, files)
        return render._view_result(pngs, cached, version(main_text), max(wanted) if total is None else total, arg, float(scale))
    except HTTPException as e:
        if e.status_code == 422:
            raise _compile_error(e, node) from None
        raise


def _link(req_base: str, token: str) -> str:
    return f"{req_base}/api/transfer/{token}"


async def export(ctx: Ctx, path: str, base: str, format: str = "pdf", pdf_standard: str = "none", pages: str = "", ppi: int = 0) -> dict:
    node = resolve(ctx, path)
    if node["kind"] == "doc":
        fmt = render._check_export_format(format)
        std, pg = render._check_pdf_standard(pdf_standard), render._check_export_pages(pages)
        pp = render._check_export_ppi(ppi) if ppi else 0
        try:
            data, mime, name = await asyncio.to_thread(render._export_doc_sync, node["doc_id"], node["title"], fmt, std, pg, pp)
        except HTTPException as e:
            if e.status_code == 422:
                raise _compile_error(e, node) from None
            raise
    elif node["kind"] in ("file", "module", "template"):
        data = await asyncio.to_thread(read_bytes, node, ctx.user)
        name = (node.get("name") or node["path"]).rsplit("/", 1)[-1]
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    else:
        raise err(400, "bad_path", "Export a document, file, module or template")
    out = {"path": node["path"], "filename": name, "mime": mime, "size_bytes": len(data),
           "url": _link(base, transfer.offer_download(ctx, name, mime, data)),
           "expires_in": int(transfer.TTL), "hint": f"curl -sS -o '{name}' '<url>'"}
    if len(data) <= INLINE_MAX:
        out["content_base64"] = base64.b64encode(data).decode()
    return out


async def upload(ctx: Ctx, path: str, base: str) -> dict:
    node = resolve(ctx, path, create=True)
    if node["kind"] not in ("doc", "new_doc", "file", "new_file", "module", "new_module", "template", "new_template"):
        raise err(400, "bad_path", "Upload to a document, attachment, module or template path")
    url = _link(base, transfer.offer_upload(ctx, node["path"]))
    return {"path": node["path"], "url": url, "expires_in": int(transfer.TTL), "max_bytes": 10 * 1024 * 1024,
            "hint": f"curl -sS -T <local-file> '{url}'  (one use; replaces the target)"}
