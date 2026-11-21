from pathlib import Path


def patch(path, pairs):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        assert s.count(a) == 1, (path, a[:70], s.count(a))
        s = s.replace(a, b)
    p.write_text(s, encoding="utf-8")


patch("backend/mcp_fs.py", [
    # resolver: names are stored sanitized, so the path we hand back is the path that works
    ('''                node["kind"] = "new_module"
            return node''', '''                node["kind"] = "new_module"
                node["name"] = clean = safe_name(name, new=True)
                node["path"] = _fmt(p, [LIB, clean])
            return node'''),
    ('''            return {**base, "kind": "folder" if is_folder else "new_folder", "folder": folder, "path": _fmt(p, rest)}''',
     '''            if not is_folder:
                from backend.routers.project_folders import folder_path
                folder = folder_path(folder)
            return {**base, "kind": "folder" if is_folder else "new_folder", "folder": folder, "path": _fmt(p, folder.split("/"))}'''),
    ('''                name = "/".join(rest[i:])
                return {**base, "role": role, "kind": "new_file"''', '''                name = safe_name("/".join(rest[i:]), new=True)
                return {**base, "role": role, "kind": "new_file"'''),
    ('''        title = rest[-1][:-4] if rest[-1].lower().endswith(".typ") else rest[-1]
        if not title.strip() or len(title) > TITLE_MAX:
            raise err(400, "bad_path", f"Document title: 1-{TITLE_MAX} characters")
        return {**base, "kind": "new_doc", "title": title.strip(), "folder": "/".join(rest[:-1]), "path": _fmt(p, rest[:-1] + [title.strip()])}''',
     '''        ext = posixpath.splitext(rest[-1])[1].lower()
        if ext in deps.ALLOWED_IMG and ext != ".typ":
            raise err(404, "not_found", f"No document {'/'.join(rest[:-1])!r} to attach {rest[-1]!r} to", hint="create the document first, then write the file under it")
        title = rest[-1][:-4] if rest[-1].lower().endswith(".typ") else rest[-1]
        if not title.strip() or len(title) > TITLE_MAX:
            raise err(400, "bad_path", f"Document title: 1-{TITLE_MAX} characters")
        folder = "/".join(rest[:-1])
        if folder:
            from backend.routers.project_folders import folder_path
            folder = folder_path(folder)
        return {**base, "kind": "new_doc", "title": title.strip(), "folder": folder, "path": _fmt(p, [*([folder] if folder else []), title.strip()])}'''),
    # read: line counting and bounds
    ('''    lines = text.split("\\n") if text else []
    sel =''', '''    lines = text.split("\\n") if text else []
    if lines and lines[-1] == "":
        lines.pop()  # the newline that ends the last line starts no line
    sel ='''),
    ('''    node = resolve(ctx, path)
    kind = node["kind"]
    if kind == "proposal":
        from backend.mcp_review import read_proposal''', '''    if offset < 1 or limit < 0:
        raise err(400, "bad_request", "offset starts at 1, limit is 0 (all) or a line count")
    node = resolve(ctx, path)
    kind = node["kind"]
    if kind == "proposal":
        from backend.mcp_review import read_proposal'''),
    ('"Give only one of content, content_base64 and from"', '"Give only one of content, content_base64 and copy_from"'),
    # stale vs missing base_version
    ('''        if not force and base_version != version(current):
            raise err(409, "stale_version", "It changed since you read it, or base_version is missing",
                      version=version(current), hint="read it first, or pass force=true")''', '''        if not force and base_version != version(current):
            raise err(409, "stale_version", "It changed since you read it" if base_version else "base_version is missing: overwriting needs the version from read",
                      version=version(current), hint="read it first, or pass force=true")'''),
    # delete: recover only for the trash; a missing folder is not found
    ('''    if kind == "proposal":
        delete_package(node["project_id"], node["id"], req, ctx.user)
    elif kind in ("folder", "new_folder"):
        need_write(node)''', '''    if kind == "proposal":
        delete_package(node["project_id"], node["id"], req, ctx.user)
        return {"deleted": node["path"], "note": "proposals are removed for good"}
    if kind == "new_folder":
        raise err(404, "not_found", f"No folder {node['path']!r}")
    if kind == "folder":
        need_write(node)'''),
    ('''            raise err(403, "forbidden", "Only the project owner can delete a project")''', '''            raise err(403, "forbidden", "Deleting a project is for people in the web app, not for keys", hint="delete its documents instead")'''),
    # move: clearer errors, trash restore reports where it landed
    ('''    if _is_convert(node, dest):
        if not _proposing(ctx, node):''', '''    if kind == "file" and dest["kind"] == "new_doc" and not node["name"].lower().endswith(".typ"):
        raise err(400, "bad_path", "Only .typ files become documents; rename a file with a path inside its own document")
    if _is_convert(node, dest):
        if not _proposing(ctx, node):'''),
    ('''        restore_doc(entry, fake_request(ctx.user), ctx.user)
        return {"restored": entry}
    return {"restored": entry, **trash.restore(ctx.user, entry)}''', '''        restore_doc(entry, fake_request(ctx.user), ctx.user)
        con = db.connect()
        try:
            r = con.execute("SELECT d.title,d.folder,p.title AS pt FROM docs d JOIN projects p ON p.id=d.project_id WHERE d.id=?", (entry,)).fetchone()
        finally:
            con.close()
        where = "/" + "/".join(x for x in (r["pt"], r["folder"], r["title"]) if x) if r else ""
        return {"restored": entry, "path": where, "note": "restored to its original place; `to` is ignored"}
    return {"restored": entry, "note": "restored to its original place; `to` is ignored", **trash.restore(ctx.user, entry)}'''),
    # conversions honour the requested module name
    ('''    body = rp.ConvertEntry(doc_id=node.get("doc_id", "") if node["kind"] == "file" else "", name=node["name"], to=to,
                           title=dest.get("title", ""), folder=dest.get("folder", ""))''', '''    body = rp.ConvertEntry(doc_id=node.get("doc_id", "") if node["kind"] == "file" else "", name=node["name"], to=to,
                           title=dest.get("title", ""), folder=dest.get("folder", ""), target=dest.get("name", "") if to == "module" else "")'''),
    ('''rp.ConvertEntry(doc_id=node["doc_id"], document=True, to="module"), req, ctx.user)''', '''rp.ConvertEntry(doc_id=node["doc_id"], document=True, to="module", target=dest["name"]), req, ctx.user)'''),
    # search: module names, and a path or kind that exists
    ('''    q = search.normalize_query(query)
    if len(q) < search.MIN_Q:
        raise err(400, "bad_request", "Search needs at least 2 characters")''', '''    q = search.normalize_query(query)
    if len(q) < search.MIN_Q:
        raise err(400, "bad_request", "Search needs at least 2 characters")
    if kind and kind not in ("doc", "file", "module", "template", "trash"):
        raise err(400, "bad_request", "kind is one of doc, file, module, template, trash")
    if path.strip("/"):
        resolve(ctx, path, create=path.endswith("/"))'''),
    ('''        for h in named:
            p = doc_path(h["id"])''', '''        for pid, pname in names.items():
            for r in con.execute("SELECT name FROM project_resources WHERE project_id=? AND name LIKE ? ESCAPE '\\\\'", (pid, "%" + q.replace("%", "").replace("_", "") + "%")):
                p = f"/{pname}/{LIB}/{r['name']}"
                if p not in seen:
                    seen.add(p)
                    hits.append({"path": p, "kind": "module", "count": 0, "line": 0, "snippet": ""})
        for h in named:
            p = doc_path(h["id"])'''),
])

patch("backend/routers/projects.py", [
    ('''    document: bool = False  # doc_id is a document itself (name ignored): it becomes a module''', '''    document: bool = False  # doc_id is a document itself (name ignored): it becomes a module
    target: str = Field(default='', max_length=240)  # module name to create (default: the old name)'''),
    ('''    if b.to == 'module':
        made = save_resource(project_id, ResourceSave(name=resource_name(name, new=True), content=text), req, user)''', '''    if b.document and con_files(b.doc_id):
        raise HTTPException(409, 'This document has attachments; move or delete them first')
    if b.to == 'module':
        made = save_resource(project_id, ResourceSave(name=resource_name(b.target or name, new=True), content=text), req, user)'''),
    ('''@router.post('/api/projects/{project_id}/convert')''', '''def con_files(doc_id: str) -> bool:
    return bool(store.list(doc_id))


@router.post('/api/projects/{project_id}/convert')'''),
])

patch("backend/mcp_review.py", [
    ('''    node = resolve(ctx, op["path"], create=kind == "write")
    if kind == "write":''', '''    node = resolve(ctx, op["path"], create=kind == "write")
    if node.get("project_id") != pid:
        raise err(400, "bad_path", f"{op['path']} is not in this project", hint="every op path starts with the project path")
    if kind == "write":'''),
    ('''    anchor = line
    if quote and not line:
        doc = doc_text(node["doc_id"])
        anchor = doc[:doc.find(quote)].count("\\n") + 1 if quote in doc else 1''', '''    if id:
        raise err(400, "bad_request", "id is for resolved=true/false or delete=true; reply with reply_to=<thread id>")
    anchor = line
    doc = doc_text(node["doc_id"])
    if quote:
        if quote not in doc:
            raise err(400, "bad_request", "quote is not in the document", hint="copy it from read, or use line")
        anchor = doc[:doc.find(quote)].count("\\n") + 1 if not line else line
    if line > len(doc.split("\\n")):
        raise err(400, "bad_request", f"line {line} is past the end ({len(doc.splitlines())} lines)")'''),
])

patch("backend/mcp_render.py", [
    ('''    diags = [{**x, "file": _label(x.get("file"), node)} for x in d.get("diagnostics", [])]
    return err(422, "compile_error", d.get("message", "compile error"), diagnostics=diags)''', '''    diags = [{**x, "file": _label(x.get("file"), node)} for x in d.get("diagnostics", [])]
    return err(422, "compile_error", _clean(d.get("message", "compile error"), node), diagnostics=diags)


def _clean(text: str, node: dict) -> str:
    """Compiler output without the server's temp directory."""
    out = []
    for word in text.split(" "):
        parts = word.replace("\\\\", "/").split("/")
        hit = next((i for i, seg in enumerate(parts) if seg.startswith(("check-doc-", "export-doc-", "mcp-view-"))), None)
        out.append("/".join(parts[hit + 1:]) if hit is not None else word)
    return " ".join(out).replace(render.ENTRY, node["path"])'''),
    ('''        if not pages:
            info = await asyncio.to_thread(render.check_source, main_text, files)
            return {"path": node["path"], "ok": True, **info}
        wanted = render._expand_pages(pages)''', '''        info = await asyncio.to_thread(render.check_source, main_text, files)
        if not pages:
            return {"path": node["path"], "ok": True, **info, "warnings": [{**w, "file": _label(w.get("file"), node)} for w in info["warnings"]]}
        wanted = render._expand_pages(pages)
        if info["pages"] and max(wanted) > info["pages"]:
            raise err(400, "bad_request", f"The document has {info['pages']} page(s); pages {pages!r} is out of range")'''),
])

patch("backend/mcp_server.py", [
    ('''    if retry := (e.headers or {}).get("Retry-After"):
        d["retry_after"] = int(retry)''', '''    if retry := (e.headers or {}).get("Retry-After"):
        d["retry_after"] = int(retry)
    elif e.status_code == 429:
        d["retry_after"] = 60
        d.setdefault("hint", "wait and retry once; the limit is per minute")'''),
    ('''    """Export a document as pdf, svg, png or zip (sources), or fetch any file/module/template. Returns a one-time download url (curl it) and, when small, content_base64."""''',
     '''    """Export a document as pdf, svg, png (several pages arrive as a zip) or zip (sources), or fetch any file/module/template. ppi 72-300 for png. Returns a download url valid for 5 minutes (curl it) and, when small, content_base64."""'''),
    ('''move /.trash/<id> (to="/")''', '''move /.trash/<id> (to="/"; it returns to its original place)'''),
])
print("ok")
