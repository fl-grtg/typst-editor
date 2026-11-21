"""Agent filesystem: one path grammar over projects, documents, attachments, modules and templates.

    /                                  projects ("Title"; foreign ones "Title@owner"), /.templates, /.trash
    /{Project}/{folder}/{Document}     a document, its text (a trailing .typ is accepted)
    /{Project}/{folder}/{Document}/{file}   an attachment of that document
    /{Project}/.library/{module}       shared project module
    /{Project}/.proposals/{id}         proposal package
    /.templates/{name}                 private template
    /.trash/{id}                       deleted entry

A document is its title; folders exist by use. Versions are content hashes of the live text.
Writes go through the same routes as the UI (quota, locks, trash, notifications); documents
are edited in the live Yjs room as minimal spans so concurrent typing survives.
"""
from __future__ import annotations

import asyncio
import base64
import difflib
import hashlib
import io
import posixpath
import re
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request, UploadFile

from backend import db, deps, search, sync
from backend.constants import MAX_TXT, TITLE_MAX, UPLOAD_MAX
from backend.services import apikeys, projects, quota, resources, trash
from backend.services import snapshots as snapsvc
from backend.services.docfiles import safe_name, store

TEXT = deps.TEXT_SUFFIX
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
LIB, TPL, PROP, TRASH = ".library", ".templates", ".proposals", ".trash"
LIST_MAX = 500
SEARCH_MAX = 30
CONTEXT = 2  # lines around an ambiguous anchor


@dataclass
class Ctx:
    user: str
    cap: str = "owner"  # key role: editor | reviewer (owner = web session)
    author: str = ""  # key name, shown on comments and packages
    mode: str = "auto"  # key mode: auto | direct | propose


def err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message, **extra})


def fake_request(user: str) -> Request:
    """Router-backed writes keep their per-user rate limit bucket."""
    return Request({"type": "http", "client": ("mcp:" + user, 0), "headers": []})


def version(data: str | bytes) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()[:16]


def is_text(name: str) -> bool:
    return posixpath.splitext(name)[1].lower() in TEXT


# --- resolver -------------------------------------------------------------------------------

def _segs(path: str) -> tuple[list[str], bool]:
    path = path if path.startswith("/") else "/" + (path or "")
    segs = [s for s in path.split("/") if s]
    if any(s in (".", "..") for s in segs):
        raise err(400, "bad_path", "No . or .. in paths")
    return segs, path.endswith("/") and bool(segs)


def visible_projects(con, user: str) -> list[dict]:
    rows = con.execute(
        "SELECT DISTINCT p.id,p.owner,p.title FROM projects p "
        "LEFT JOIN project_members m ON m.project_id=p.id AND m.username=? "
        "LEFT JOIN docs d ON d.project_id=p.id LEFT JOIN shares s ON s.doc_id=d.id AND s.username=? "
        "WHERE p.archived=0 AND (p.owner=? OR m.username IS NOT NULL OR (s.username IS NOT NULL AND d.trashed=0)) "
        "ORDER BY p.title", (user, user, user)).fetchall()
    return [{"id": r["id"], "owner": r["owner"], "title": r["title"],
             "name": r["title"] if r["owner"] == user else f"{r['title']}@{r['owner']}"} for r in rows]


def _project(con, ctx: Ctx, seg: str) -> dict:
    low = seg.lower()
    ps = visible_projects(con, ctx.user)
    hit = [p for p in ps if p["name"].lower() == low] or [p for p in ps if p["title"].lower() == low]
    if len(hit) == 1:
        return hit[0]
    if hit:
        raise err(409, "ambiguous", f"Several projects are called {seg!r}", candidates=[p["name"] for p in hit])
    raise err(404, "not_found", f"No project {seg!r}", hint="ls / lists the projects you can see")


def _project_role(con, ctx: Ctx, pid: str) -> str:
    try:
        role = projects.role(con, pid, ctx.user)
    except HTTPException:
        return "guest"
    return apikeys.cap_min(ctx.cap, role)


def _doc_row(con, pid: str, folder: str, title: str):
    for t in (title, title[:-4] if title.lower().endswith(".typ") else ""):
        if t:
            row = con.execute("SELECT id,title,folder,owner,updated_at FROM docs WHERE project_id=? AND folder=? "
                              "AND title=? COLLATE NOCASE AND trashed=0", (pid, folder, t)).fetchone()
            if row:
                return row


def _find_doc(con, pid: str, rest: list[str]):
    """Longest document path wins; an attachment path only counts while that file exists."""
    for i in range(len(rest), 0, -1):
        row = _doc_row(con, pid, "/".join(rest[:i - 1]), rest[i - 1])
        if row and (i == len(rest) or con.execute("SELECT 1 FROM files WHERE doc_id=? AND path=? COLLATE NOCASE",
                                                  (row["id"], "/".join(rest[i:]))).fetchone()):
            return row, "/".join(rest[i:])
    return None, ""


def _fmt(p: dict, rest: list[str]) -> str:
    return "/" + "/".join([p["name"], *rest])


def resolve(ctx: Ctx, path: str, create: bool = False) -> dict:
    """Node for a path. With create=True a missing path yields kind new_* instead of 404."""
    segs, slash = _segs(path)
    if not segs:
        return {"kind": "root", "path": "/"}
    if segs[0] == TPL:
        return _template_node(ctx, segs, create)
    if segs[0] == TRASH:
        return {"kind": "trash" if len(segs) == 1 else "trash_item", "path": "/" + "/".join(segs), "id": "/".join(segs[1:])}
    con = db.connect()
    try:
        try:
            p = _project(con, ctx, segs[0])
        except HTTPException as e:
            if create and e.status_code == 404 and len(segs) == 1:
                title = segs[0].strip()
                if not title or len(title) > TITLE_MAX or "@" in title:
                    raise err(400, "bad_path", f"Project name: 1-{TITLE_MAX} characters, no @") from None
                return {"kind": "new_project", "title": title, "path": "/" + title}
            raise
        rest = segs[1:]
        base = {"project_id": p["id"], "owner": p["owner"], "pname": p["name"], "role": _project_role(con, ctx, p["id"])}
        if not rest:
            return {**base, "kind": "project", "path": _fmt(p, [])}
        if rest[0] == LIB:
            name = "/".join(rest[1:])
            node = {**base, "kind": "library" if not name else "module", "name": name, "path": _fmt(p, rest)}
            if name and not con.execute("SELECT 1 FROM project_resources WHERE project_id=? AND name=?", (p["id"], name)).fetchone():
                if not create:
                    raise err(404, "not_found", f"No module {name!r}", hint=f"ls {_fmt(p, [LIB])}")
                node["kind"] = "new_module"
                node["name"] = clean = safe_name(name, new=True)
                node["path"] = _fmt(p, [LIB, clean])
            return node
        if rest[0] == PROP:
            node = {**base, "kind": "proposals" if len(rest) == 1 else "proposal", "id": "/".join(rest[1:]), "path": _fmt(p, rest)}
            return node
        row, attach = _find_doc(con, p["id"], rest)
        if row:
            role = apikeys.cap_min(ctx.cap, db.role_on(con, ctx.user, row["id"]) or "")
            if not role:
                raise err(404, "not_found", f"No document {'/'.join(rest)!r}")
            dpath = _fmt(p, [x for x in [row["folder"], row["title"]] if x])
            node = {**base, "role": role, "doc_id": row["id"], "title": row["title"], "folder": row["folder"] or "",
                    "doc_owner": row["owner"], "kind": "file" if attach else "doc", "path": dpath + ("/" + attach if attach else ""),
                    "name": attach}
            return node
        folder = "/".join(rest)
        is_folder = con.execute("SELECT 1 FROM project_folders WHERE project_id=? AND path=? UNION ALL SELECT 1 FROM docs WHERE project_id=? "
                                "AND trashed=0 AND (folder=? OR folder LIKE ?) LIMIT 1", (p["id"], folder, p["id"], folder, folder + "/%")).fetchone()
        if slash or (is_folder and not create):
            if not (create or is_folder):
                raise err(404, "not_found", f"No folder {folder!r}")
            if not is_folder:
                from backend.routers.project_folders import folder_path
                folder = folder_path(folder)
            return {**base, "kind": "folder" if is_folder else "new_folder", "folder": folder, "path": _fmt(p, folder.split("/"))}
        if not create:
            raise err(404, "not_found", f"Nothing at {path!r}", hint=f"ls {_fmt(p, rest[:-1])}")
        for i in range(len(rest) - 1, 0, -1):  # the longest existing document in front of the name owns the file
            parent = _doc_row(con, p["id"], "/".join(rest[:i - 1]), rest[i - 1])
            if parent and not con.execute("SELECT 1 FROM project_folders WHERE project_id=? AND path=?", (p["id"], "/".join(rest[:i]))).fetchone():
                role = apikeys.cap_min(ctx.cap, db.role_on(con, ctx.user, parent["id"]) or "")
                name = safe_name("/".join(rest[i:]), new=True)
                return {**base, "role": role, "kind": "new_file", "doc_id": parent["id"], "name": name, "title": parent["title"],
                        "path": _fmt(p, [x for x in [parent["folder"], parent["title"]] if x] + [name])}
        ext = posixpath.splitext(rest[-1])[1].lower()
        if ext in deps.ALLOWED_IMG and ext != ".typ":
            raise err(404, "not_found", f"No document {'/'.join(rest[:-1])!r} to attach {rest[-1]!r} to", hint="create the document first, then write the file under it")
        title = rest[-1][:-4] if rest[-1].lower().endswith(".typ") else rest[-1]
        if not title.strip() or len(title) > TITLE_MAX:
            raise err(400, "bad_path", f"Document title: 1-{TITLE_MAX} characters")
        folder = "/".join(rest[:-1])
        if folder:
            from backend.routers.project_folders import folder_path
            folder = folder_path(folder)
        return {**base, "kind": "new_doc", "title": title.strip(), "folder": folder, "path": _fmt(p, [*([folder] if folder else []), title.strip()])}
    finally:
        con.close()


def _template_node(ctx: Ctx, segs: list[str], create: bool) -> dict:
    if len(segs) == 1:
        return {"kind": "templates", "path": "/" + TPL}
    name = "/".join(segs[1:])
    con = db.connect()
    try:
        row = con.execute("SELECT updated_at FROM templates WHERE owner=? AND name=?", (ctx.user, name)).fetchone()
    finally:
        con.close()
    node = {"kind": "template", "name": name, "role": apikeys.cap_min(ctx.cap, "owner"), "path": f"/{TPL}/{name}"}
    if not row:
        if not create:
            raise err(404, "not_found", f"No template {name!r}", hint=f"ls /{TPL}")
        node["kind"] = "new_template"
    return node


# --- reading ----------------------------------------------------------------------------------

def need_write(node: dict) -> None:
    if node.get("role") not in ("owner", "editor"):
        raise err(403, "forbidden", "Your key or role may only read, comment and propose")


def doc_text(doc_id: str) -> str:
    live = sync.room_text(doc_id)
    if live is not None:
        return live
    con = db.connect()
    try:
        row = con.execute("SELECT content FROM docs WHERE id=?", (doc_id,)).fetchone()
    finally:
        con.close()
    if not row:
        raise err(404, "not_found", "Document gone")
    return row["content"] or ""


def read_bytes(node: dict, user: str = "") -> bytes:
    kind = node["kind"]
    if kind == "doc":
        return doc_text(node["doc_id"]).encode()
    if kind == "file":
        try:
            return store.get(node["doc_id"], node["name"])
        except FileNotFoundError:
            raise err(404, "not_found", "File gone") from None
    con = db.connect()
    try:
        if kind == "module":
            row = con.execute("SELECT content FROM project_resources WHERE project_id=? AND name=?", (node["project_id"], node["name"])).fetchone()
        elif kind == "template":
            row = con.execute("SELECT content FROM templates WHERE owner=? AND name=?", (user, node["name"])).fetchone()
        else:
            raise err(400, "not_readable", f"{node['path']} is not a file", hint="ls it instead")
    finally:
        con.close()
    if not row:
        raise err(404, "not_found", "Gone")
    return (row["content"] or "").encode()


def text_of(ctx: Ctx, node: dict) -> str:
    if node["kind"] == "file" and not is_text(node["name"]):
        raise err(400, "binary", f"{node['path']} is binary", hint="read shows images; export or upload move other files")
    return read_bytes(node, ctx.user).decode("utf-8", errors="replace")


HEADING = re.compile(r"^(=+)\s+(.*)$")
LABEL = re.compile(r"<([\w:.-]+)>")
LET = re.compile(r"^\s*#let\s+([\w-]+)")
IMPORT = re.compile(r'#?(?:include|import|image|bibliography|csv|json|yaml|toml|xml|read)\s*\(?\s*"([^"\n]+)"')


def outline(node: dict, text: str) -> dict:
    """Headings, labels, lets and imports (with what they resolve to) of a document."""
    con = db.connect()
    try:
        local = {r[0].lower(): r[0] for r in con.execute("SELECT path FROM files WHERE doc_id=?", (node["doc_id"],))}
        mods = {r[0].lower(): r[0] for r in con.execute("SELECT name FROM project_resources WHERE project_id=?", (node["project_id"],))}
    finally:
        con.close()
    out: dict = {"headings": [], "labels": [], "lets": [], "imports": []}
    for n, line in enumerate(text.split("\n"), 1):
        if m := HEADING.match(line):
            out["headings"].append({"line": n, "level": len(m[1]), "text": m[2].strip()})
        out["labels"] += [{"line": n, "label": x} for x in LABEL.findall(line)]
        if m := LET.match(line):
            out["lets"].append({"line": n, "name": m[1]})
        for ref in IMPORT.findall(line):
            key = posixpath.normpath(ref.replace("\\", "/")).lstrip("/").lower()
            hit = (f"file {local[key]}" if key in local else f"module {mods[key]}" if key in mods else
                   "package" if ref.startswith("@") else "")
            out["imports"].append({"line": n, "ref": ref, "resolves_to": hit or None})
    return out


def open_comments(doc_id: str) -> list[dict]:
    con = db.connect()
    try:
        rows = con.execute("SELECT id,username,author,anchor,quote,text,parent_id,created_at FROM comments "
                           "WHERE doc_id=? AND resolved=0 ORDER BY created_at", (doc_id,)).fetchall()
    finally:
        con.close()
    threads: dict[str, dict] = {}
    for r in rows:
        who = r["author"] or r["username"]
        if not r["parent_id"]:
            threads[r["id"]] = {"id": r["id"], "line": r["anchor"], "quote": r["quote"], "by": who, "text": r["text"], "replies": []}
    for r in rows:
        if r["parent_id"] in threads:
            threads[r["parent_id"]]["replies"].append({"id": r["id"], "by": r["author"] or r["username"], "text": r["text"]})
    return list(threads.values())


def _window(text: str, offset: int, limit: int) -> tuple[str, int]:
    lines = text.split("\n") if text else []
    sel = lines[max(offset, 1) - 1:] if not limit else lines[max(offset, 1) - 1:max(offset, 1) - 1 + limit]
    return "\n".join(sel), len(lines) - (1 if lines and lines[-1] == "" else 0)  # the newline that ends the last line starts no line


def read(ctx: Ctx, path: str, offset: int = 1, limit: int = 0, want_outline: bool = False, snapshot: str = ""):
    if offset < 1 or limit < 0:
        raise err(400, "bad_request", "offset starts at 1, limit is 0 (all) or a line count")
    node = resolve(ctx, path)
    kind = node["kind"]
    if kind == "proposal":
        from backend.mcp_review import read_proposal
        return read_proposal(ctx, node)
    if kind == "file" and not is_text(node["name"]):
        data = read_bytes(node)
        meta = {"path": node["path"], "binary": True, "size": len(data), "version": version(data)}
        if posixpath.splitext(node["name"])[1].lower() in IMAGES:
            return meta, data
        if len(data) <= 128 * 1024:
            meta["content_base64"] = base64.b64encode(data).decode()
        else:
            meta["hint"] = "Large binary: use export to get a download link"
        return meta, None
    if snapshot:
        if kind != "doc":
            raise err(400, "bad_request", "Only documents keep versions")
        con = db.connect()
        try:
            row = con.execute("SELECT content,label,created_at FROM snapshots WHERE id=? AND doc_id=?", (snapshot, node["doc_id"])).fetchone()
        finally:
            con.close()
        if not row:
            raise err(404, "not_found", "No such version", hint="ls the document with versions=true")
        text = row["content"] or ""
    else:
        text = text_of(ctx, node)
    content, total = _window(text, offset, limit)
    out = {"path": node["path"], "kind": kind, "version": version(text), "total_lines": total, "content": content}
    if kind == "doc" and not snapshot:
        out["live"] = sync.room_text(node["doc_id"]) is not None
        out["comments"] = open_comments(node["doc_id"])
        if want_outline:
            out["outline"] = outline(node, text)
    return out, None


# --- listing ----------------------------------------------------------------------------------

def _entries(con, ctx: Ctx, node: dict) -> list[dict]:
    pid = node["project_id"]
    guest = node["role"] == "guest"
    docs, out = {}, []
    open_c = {r[0]: r[1] for r in con.execute(
        "SELECT c.doc_id,COUNT(*) FROM comments c JOIN docs d ON d.id=c.doc_id WHERE d.project_id=? AND c.resolved=0 AND c.parent_id IS NULL GROUP BY c.doc_id", (pid,))}
    for r in con.execute("SELECT id,title,folder,length(content) AS size,updated_at FROM docs WHERE project_id=? AND trashed=0 ORDER BY folder,title", (pid,)):
        if guest and not db.role_on(con, ctx.user, r["id"]):
            continue
        path = "/".join(x for x in (r["folder"], r["title"]) if x)
        docs[r["id"]] = path
        e = {"path": path, "kind": "doc", "size": r["size"], "updated_at": r["updated_at"]}
        if open_c.get(r["id"]):
            e["open_comments"] = open_c[r["id"]]
        out.append(e)
    for r in con.execute("SELECT f.doc_id,f.path,f.size FROM files f JOIN docs d ON d.id=f.doc_id WHERE d.project_id=? AND d.trashed=0 ORDER BY f.path", (pid,)):
        if r["doc_id"] in docs:
            out.append({"path": f"{docs[r['doc_id']]}/{r['path']}", "kind": "file", "size": r["size"]})
    if not guest:
        for r in con.execute("SELECT name,length(content) AS size,updated_at FROM project_resources WHERE project_id=? ORDER BY name", (pid,)):
            out.append({"path": f"{LIB}/{r['name']}", "kind": "module", "size": r["size"], "updated_at": r["updated_at"]})
        out += [{"path": r[0], "kind": "folder"} for r in con.execute("SELECT path FROM project_folders WHERE project_id=?", (pid,))]
        n = con.execute("SELECT COUNT(*) FROM suggestion_packages WHERE project_id=? AND json_array_length(files)>0", (pid,)).fetchone()[0]
        out.append({"path": PROP, "kind": "proposals", "count": n})
    return out


def _tree(entries: list[dict], prefix: str, depth: int) -> list[dict]:
    base = prefix.strip("/") + "/" if prefix.strip("/") else ""
    known = {e["path"] for e in entries}
    out, seen = [], set()
    for e in sorted(entries, key=lambda e: e["path"]):
        if not e["path"].startswith(base) or e["path"] == base.rstrip("/"):
            continue
        rel = e["path"][len(base):].split("/")
        if depth and len(rel) > depth:
            d = base + "/".join(rel[:depth])
            if d not in known and d not in seen:
                seen.add(d)
                out.append({"path": d, "kind": "folder"})
            continue
        out.append(e)
    return out


def ls(ctx: Ctx, path: str = "/", depth: int = 1, versions: bool = False) -> dict:
    node = resolve(ctx, path)
    kind = node["kind"]
    con = db.connect()
    try:
        if kind == "root":
            items = [{"path": "/" + p["name"], "kind": "project", "role": _project_role(con, ctx, p["id"])} for p in visible_projects(con, ctx.user)]
            items += [{"path": "/" + TPL, "kind": "templates"}, {"path": "/" + TRASH, "kind": "trash"}]
            return {"path": "/", "entries": items}
        if kind == "templates":
            rows = con.execute("SELECT name,length(content) AS size,updated_at FROM templates WHERE owner=? ORDER BY name", (ctx.user,)).fetchall()
            return {"path": node["path"], "entries": [{"path": f"/{TPL}/{r['name']}", "kind": "template", "size": r["size"], "updated_at": r["updated_at"]} for r in rows]}
        if kind == "trash":
            return {"path": node["path"], "entries": _trash_entries(con, ctx)}
        if kind in ("proposals", "proposal"):
            from backend.mcp_review import list_proposals
            return list_proposals(ctx, node)
        if kind in ("project", "folder", "doc", "library", "new_folder"):
            ents = _entries(con, ctx, node)
            prefix = "" if kind == "project" else node["path"].split("/", 2)[2] if node["path"].count("/") > 1 else ""
            top = "/" + node["pname"] + "/"
            out = {"path": node["path"], "entries": [{**e, "path": top + e["path"]} for e in _tree(ents, prefix, depth)[:LIST_MAX]]}
            if kind == "doc":
                out["version"] = version(doc_text(node["doc_id"]))
                if versions:
                    rows = con.execute("SELECT id,label,created_at FROM snapshots WHERE doc_id=? ORDER BY created_at DESC LIMIT 30", (node["doc_id"],)).fetchall()
                    out["versions"] = [dict(r) for r in rows]
            return out
        if kind == "file":
            data = read_bytes(node)
            return {"path": node["path"], "entries": [{"path": node["path"], "kind": "file", "size": len(data), "version": version(data)}]}
        return {"path": node["path"], "entries": [{"path": node["path"], "kind": kind}]}
    finally:
        con.close()


def _trash_entries(con, ctx: Ctx) -> list[dict]:
    out = [{"path": f"/{TRASH}/{r['id']}", "kind": "doc", "name": r["title"], "deleted_at": r["updated_at"]}
           for r in con.execute("SELECT id,title,updated_at FROM docs WHERE owner=? AND trashed=1 ORDER BY updated_at DESC", (ctx.user,))]
    out += [{"path": f"/{TRASH}/{r['id']}", "kind": {"resource": "module", "personal": "template"}.get(r["kind"], r["kind"]),
             "name": r["name"], "deleted_at": r["created_at"]}
            for r in con.execute("SELECT id,kind,name,created_at FROM trash_entries WHERE owner=? ORDER BY created_at DESC", (ctx.user,))]
    return out


# --- editing ----------------------------------------------------------------------------------

def apply_edits(text: str, edits: list[dict]) -> tuple[str, int]:
    """All edits match the text as it is now (none sees another's result). Returns (new text, replaced)."""
    spans = []
    for e in edits:
        old, new = e["old"], e["new"]
        if not old:
            raise err(400, "bad_request", "old must not be empty", hint="quote 2-3 lines around the change")
        starts = [m.start() for m in re.finditer(re.escape(old), text)]
        if not starts:
            near = difflib.get_close_matches(old.strip().split("\n")[0], text.split("\n"), n=1, cutoff=0.6)
            hit = {"closest": {"line": text.split("\n").index(near[0]) + 1, "text": near[0]}} if near else {}
            raise err(409, "anchor_gone", "old was not found; read the document again", **hit)
        if len(starts) > 1 and not e.get("all"):
            cand = [{"line": text[:s].count("\n") + 1, "context": "\n".join(text.split("\n")[max(0, text[:s].count("\n") - CONTEXT):text[:s].count("\n") + CONTEXT + 1])} for s in starts[:5]]
            raise err(409, "anchor_ambiguous", f"old matches {len(starts)} times; add context or set all=true", candidates=cand)
        spans += [(s, s + len(old), new) for s in (starts if e.get("all") else starts[:1])]
    spans.sort()
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:], strict=False)):
        raise err(400, "bad_request", "Edits overlap")
    for start, end, new in reversed(spans):
        text = text[:start] + new + text[end:]
    return text, len(spans)


def _fresh(base_version: str, text: str, strict: bool) -> bool:
    """True when the caller saw an older version; strict (write) refuses, edit only reports."""
    changed = bool(base_version) and base_version != version(text)
    if changed and strict:
        raise err(409, "stale_version", "The text changed since you read it", version=version(text), hint="read again and redo the change")
    return changed


async def set_doc(ctx: Ctx, doc_id: str, fn) -> tuple[str, str]:
    owner = quota.doc_owner(doc_id, ctx.user)

    def guarded(old: str) -> str:
        new = fn(old)
        if len(new.encode()) > MAX_TXT:
            raise err(413, "too_large", f"A document holds at most {MAX_TXT // 1000} KB of text")
        quota.check_quota(owner, max(0, len(new.encode()) - len(old.encode())))
        return new

    con = db.connect()
    try:
        row = con.execute("SELECT trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
        role = apikeys.cap_min(ctx.cap, db.role_on(con, ctx.user, doc_id) or "")
    finally:
        con.close()
    if not row:
        raise err(404, "not_found", "Document gone")
    if row["trashed"]:
        raise err(410, "gone", "The document is in the trash; restore it first")
    if role not in ("owner", "editor"):
        raise err(403, "forbidden", "Your role may only read, comment and propose")
    old, new = await sync.edit_doc(doc_id, guarded)
    if old != new:
        try:
            snapsvc.auto_snap(doc_id, old, label=f"agent:{ctx.author or ctx.user}")
        except HTTPException:
            pass
    return old, new


def _save_text(ctx: Ctx, node: dict, text: str) -> None:
    """Overwrite or create a file, module or template through the UI's save routes."""
    from backend.routers import projects as rp
    from backend.routers import templates as rt
    from backend.routers.files import upload_file
    from backend.schemas import TplSave

    req, kind = fake_request(ctx.user), node["kind"]
    if len(text.encode()) > MAX_TXT:
        raise err(413, "too_large", f"Text files hold at most {MAX_TXT // 1000} KB")
    if kind in ("file", "new_file"):
        upload_file(node["doc_id"], UploadFile(file=io.BytesIO(text.encode()), filename=node["name"]), req, ctx.user)
    elif kind in ("module", "new_module"):
        ver = None
        if kind == "module":
            con = db.connect()
            try:
                ver = con.execute("SELECT updated_at FROM project_resources WHERE project_id=? AND name=?", (node["project_id"], node["name"])).fetchone()[0]
            finally:
                con.close()
        rp.save_resource(node["project_id"], rp.ResourceSave(name=node["name"], content=text, version=ver), req, ctx.user)
    else:
        rt.save_template(TplSave(name=node["name"], content=text), req, ctx.user)


def _proposing(ctx: Ctx, node: dict) -> bool:
    """Reviewers and shared projects (key mode auto) hand changes in as proposals."""
    if node["kind"] in ("template", "new_template", "new_project", "new_folder", "project", "templates"):
        return False
    if node.get("role") not in ("owner", "editor"):
        return True
    if ctx.mode != "auto":
        return ctx.mode == "propose"
    con = db.connect()
    try:
        return con.execute("SELECT 1 FROM project_members WHERE project_id=?", (node["project_id"],)).fetchone() is not None
    finally:
        con.close()


async def propose(ctx: Ctx, node: dict, op: dict, package: str = "") -> dict:
    from backend import mcp_review

    return await mcp_review.propose(ctx, node["project_id"], [op], package=package)


def source(ctx: Ctx, content: str | None, content_base64: str, from_path: str) -> tuple[bytes | None, bool]:
    """(bytes, came as text) from exactly one of content, content_base64 or an existing path."""
    if sum(x not in (None, "") for x in (content, content_base64, from_path)) > 1:
        raise err(400, "bad_request", "Give only one of content, content_base64 and copy_from")
    if content_base64:
        try:
            return base64.b64decode(content_base64, validate=True), False
        except ValueError:
            raise err(400, "bad_request", "content_base64 is not valid base64") from None
    if from_path:
        src = resolve(ctx, from_path)
        data = read_bytes(src, ctx.user)
        return data, src["kind"] != "file" or is_text(src["name"])
    return (content.encode() if content is not None else None), True


async def write(ctx: Ctx, path: str, content: str | None = None, content_base64: str = "", from_path: str = "",
                base_version: str = "", force: bool = False, package: str = "") -> dict:
    data, as_text = source(ctx, content, content_base64, from_path)
    node = resolve(ctx, path, create=True)
    kind = node["kind"]
    created = kind.startswith("new_")
    if kind == "new_project":
        from backend.routers.projects import ProjectTitle, create_project
        r = create_project(ProjectTitle(title=node["title"]), fake_request(ctx.user), ctx.user)
        return {"path": "/" + node["title"], "id": r["id"], "created": True}
    if kind in ("new_folder", "folder"):
        need_write(node)
        from backend.routers.project_folders import FolderPath, create_folder
        create_folder(node["project_id"], FolderPath(path=node["folder"]), fake_request(ctx.user), ctx.user)
        return {"path": node["path"], "created": True}
    if kind not in ("doc", "new_doc", "file", "new_file", "module", "new_module", "template", "new_template"):
        raise err(400, "bad_path", f"{node['path']} cannot be written", hint="name a document, file, module, template or folder")
    if _proposing(ctx, node):
        return await propose(ctx, node, {"op": "write", "path": path, "data": data, "text": as_text, "base_version": base_version}, package)
    need_write(node)
    data = b"" if data is None else data
    binary = kind in ("file", "new_file") and not (as_text and is_text(node["name"]))
    def check(current: bytes) -> None:
        if not force and base_version != version(current):
            raise err(409, "stale_version", "It changed since you read it" if base_version else "base_version is missing: overwriting needs the version from read",
                      version=version(current), hint="read it first, or pass force=true")

    def replaced(old: str) -> str:
        check(old.encode())
        return text

    if not created and kind != "doc":
        check(read_bytes(node, ctx.user))
    if binary or len(data) > MAX_TXT:
        if not binary or len(data) > UPLOAD_MAX:
            raise err(413, "too_large", f"Text holds at most {MAX_TXT // 1000} KB, files 10 MB; use upload for large files")
        from backend.routers.files import upload_file
        upload_file(node["doc_id"], UploadFile(file=io.BytesIO(data), filename=node["name"]), fake_request(ctx.user), ctx.user)
        return {"path": node["path"], "created": created, "version": version(data)}
    text = data.decode("utf-8", errors="replace")
    if kind == "new_doc":
        from backend.routers.projects import ProjectDoc, create_document
        r = create_document(node["project_id"], ProjectDoc(title=node["title"], folder=node["folder"], content=text), fake_request(ctx.user), ctx.user)
        return {"path": node["path"], "id": r["id"], "created": True, "version": version(text)}
    if kind == "doc":
        await set_doc(ctx, node["doc_id"], replaced)
    else:
        _save_text(ctx, node, text)
    return {"path": node["path"], "created": created, "version": version(text)}


async def edit(ctx: Ctx, path: str, edits: list[dict], base_version: str = "", package: str = "") -> dict:
    node = resolve(ctx, path)
    if node["kind"] not in ("doc", "file", "module", "template"):
        raise err(400, "bad_path", f"{node['path']} is not an editable text")
    if _proposing(ctx, node):
        return await propose(ctx, node, {"op": "edit", "path": path, "edits": edits, "base_version": base_version}, package)
    need_write(node)
    done: dict = {}

    def run(old: str) -> str:
        done["changed"] = _fresh(base_version, old, False)
        new, done["replaced"] = apply_edits(old, edits)
        return new

    if node["kind"] == "doc":
        _, new = await set_doc(ctx, node["doc_id"], run)
    else:
        new = run(text_of(ctx, node))
        _save_text(ctx, node, new)
    out = {"path": node["path"], "replaced": done["replaced"], "version": version(new)}
    if done["changed"]:
        out["changed_since"] = True
    return out


# --- move / delete ---------------------------------------------------------------------------

def ref_edits(ctx: Ctx, node: dict, new_name: str) -> list[dict]:
    """Texts that quote the old name of a moved file or module, with the quoted path rewritten."""
    old = node["name"]
    con = db.connect()
    try:
        if node["kind"] == "file":
            scope = [(node["doc_id"], node["title"])]
        else:
            scope = [(r[0], r[1]) for r in con.execute("SELECT id,title FROM docs WHERE project_id=? AND trashed=0", (node["project_id"],))]
        mods = [(r[0], r[1]) for r in con.execute("SELECT name,content FROM project_resources WHERE project_id=?", (node["project_id"],))]
    finally:
        con.close()
    targets = []
    for doc_id, title in scope:
        targets.append(({"kind": "doc", "doc_id": doc_id, "path": title}, "", doc_text(doc_id)))
        for e in store.list(doc_id):
            if e.path.lower().endswith(".typ") and not (node["kind"] == "file" and e.path == old):
                targets.append(({"kind": "file", "doc_id": doc_id, "name": e.path}, e.path, store.get(doc_id, e.path).decode("utf-8", errors="replace")))
    for name, content in mods:
        if name.lower().endswith(".typ") and not (node["kind"] == "module" and name == old):
            targets.append(({"kind": "module", "project_id": node["project_id"], "name": name}, name, content or ""))
    out = []
    for target, referrer, text in targets:
        here = posixpath.dirname(referrer)

        def fix(m: re.Match, here: str = here) -> str:
            ref = m.group(1).replace("\\", "/")
            hit = posixpath.normpath(ref.lstrip("/")) if ref.startswith("/") else posixpath.normpath(posixpath.join(here, ref))
            if hit != old:
                return m.group(0)
            return '"' + ("/" + new_name if ref.startswith("/") else posixpath.relpath(new_name, here or ".")) + '"'

        new = resources.REF_RE.sub(fix, text)
        if new != text:
            out.append({"target": target, "old": text, "new": new})
    return out


def _check_move(ctx: Ctx, node: dict, dest: dict, fix_refs: bool) -> list[dict]:
    """Validate a move inside one project; returns the reference rewrites it needs."""
    kind = node["kind"]
    if dest.get("project_id") != node["project_id"]:
        raise err(400, "bad_path", "Moves stay inside one project; copy with write(copy_from=...) and delete across projects")
    if kind == "doc" and dest["kind"] != "new_doc":
        raise err(400, "bad_path", "A document moves to another document path")
    if kind == "file" and (dest["kind"] != "new_file" or dest["doc_id"] != node["doc_id"]):
        raise err(400, "bad_path", "An attachment is renamed inside its own document")
    if kind == "module" and dest["kind"] != "new_module":
        raise err(400, "bad_path", f"A module is renamed to /{node['pname']}/{LIB}/name")
    if kind not in ("doc", "file", "module"):
        raise err(400, "bad_path", f"{node['path']} cannot be moved")
    return ref_edits(ctx, node, dest["name"]) if fix_refs and kind != "doc" else []


CONVERSIONS = (("file", "new_doc"), ("doc", "new_file"), ("file", "new_module"), ("module", "new_doc"), ("doc", "new_module"))


def _is_convert(node: dict, dest: dict) -> bool:
    return (node["kind"], dest["kind"]) in CONVERSIONS and dest.get("project_id") == node["project_id"]


def move_ops(ctx: Ctx, path: str, to: str, fix_refs: bool = True) -> list[dict]:
    """The move plus the reference rewrites it needs, as proposal operations."""
    node, dest = resolve(ctx, path), resolve(ctx, to, create=True)
    if _is_convert(node, dest):  # a conversion is the new text plus the removal of the old one
        return [{"op": "write", "path": to, "data": text_of(ctx, node).encode(), "text": True}, {"op": "delete", "path": path}]
    refs = _check_move(ctx, node, dest, fix_refs)
    return [{"op": "move", "path": path, "to": to}] + [{"op": "replace", "target": r["target"], "new": r["new"]} for r in refs]


async def move(ctx: Ctx, path: str, to: str, fix_refs: bool = True, package: str = "") -> dict:
    from backend.routers import projects as rp
    from backend.routers import templates as rt
    from backend.routers.project_folders import FolderRename, rename_folder
    from backend.schemas import TplRename

    node = resolve(ctx, path, create=path.endswith("/") and path != "/")
    kind = node["kind"]
    if kind == "trash_item":
        return await asyncio.to_thread(_restore, ctx, node)
    dest = resolve(ctx, to, create=True)
    if dest["kind"] in ("doc", "file", "module", "template", "project"):
        raise err(409, "exists", f"{dest['path']} already exists")
    req = fake_request(ctx.user)
    if kind == "project":
        if dest["kind"] != "new_project":
            raise err(400, "bad_path", "A project is renamed to /NewTitle")
        rp.rename_project(node["project_id"], rp.ProjectTitle(title=dest["title"]), req, ctx.user)
        return {"path": dest["path"]}
    if kind == "template":
        if dest["kind"] != "new_template":
            raise err(400, "bad_path", f"A template is renamed to /{TPL}/name")
        rt.rename_template(node["name"], TplRename(name=dest["name"]), req, ctx.user)
        return {"path": dest["path"]}
    if kind in ("folder", "new_folder"):
        if dest["kind"] not in ("folder", "new_folder") or dest["project_id"] != node["project_id"]:
            raise err(400, "bad_path", "A folder moves to another folder of the same project; end both paths with /")
        need_write(node)
        await asyncio.to_thread(rename_folder, node["project_id"], FolderRename(path=node["folder"], target=dest["folder"]), req, ctx.user)
        return {"path": dest["path"], "note": "References to files inside are not rewritten"}
    if kind == "file" and dest["kind"] == "new_doc" and not node["name"].lower().endswith(".typ"):
        raise err(400, "bad_path", "Only .typ files become documents; rename a file with a path inside its own document")
    if _is_convert(node, dest):
        if not _proposing(ctx, node):
            return await _convert(ctx, node, dest)
        from backend import mcp_review

        return await mcp_review.propose(ctx, node["project_id"], move_ops(ctx, path, to, fix_refs), package=package)
    refs = _check_move(ctx, node, dest, fix_refs)
    if _proposing(ctx, node):
        from backend import mcp_review

        return await mcp_review.propose(ctx, node["project_id"], move_ops(ctx, path, to, fix_refs), package=package)
    need_write(node)
    if kind == "doc":
        _move_doc(ctx, node, dest)
    else:
        await asyncio.to_thread(_rename_entry, ctx, node, dest)
    for r in refs:
        await replace_text(ctx, r["target"], r["new"])
    return {"path": dest["path"], "updated_references": len(refs)}


async def _convert(ctx: Ctx, node: dict, dest: dict) -> dict:
    """A .typ file or module becomes a document or module, or a document becomes an attachment of another one."""
    from backend.routers import projects as rp

    need_write(node)
    req = fake_request(ctx.user)
    if node["kind"] == "doc" and dest["kind"] == "new_module":
        await rp.convert_entry(node["project_id"], rp.ConvertEntry(doc_id=node["doc_id"], document=True, to="module", target=dest["name"]), req, ctx.user)
        return {"path": dest["path"], "converted": "document to module"}
    if node["kind"] == "doc":
        await rp.demote_doc(node["project_id"], rp.Demote(doc_id=node["doc_id"], target_doc_id=dest["doc_id"], name=dest["name"]), req, ctx.user)
        return {"path": dest["path"], "converted": "document to file"}
    if not node["name"].lower().endswith(".typ"):
        raise err(400, "bad_path", "Only .typ files can be converted")
    to: Literal["document", "module"] = "module" if dest["kind"] == "new_module" else "document"
    broken = [] if to == "module" else sorted({_ref_path(r["target"], node) for r in ref_edits(ctx, node, "gone.typ")})
    body = rp.ConvertEntry(doc_id=node.get("doc_id", "") if node["kind"] == "file" else "", name=node["name"], to=to,
                           title=dest.get("title", ""), folder=dest.get("folder", ""), target=dest.get("name", "") if to == "module" else "")
    r = await rp.convert_entry(node["project_id"], body, req, ctx.user)
    out = {"path": dest["path"], "converted": f"{node['kind']} to {to}", **{k: v for k, v in r.items() if k == "id"}}
    if broken:
        out["broken_references"] = broken
        out["hint"] = "These texts still include the file, which is no longer an attachment; edit them"
    return out


def _ref_path(target: dict, node: dict) -> str:
    if target["kind"] == "doc":
        return doc_path_of(target["doc_id"], node)
    if target["kind"] == "file":
        return f"{doc_path_of(target['doc_id'], node)}/{target['name']}"
    return f"/{node['pname']}/{LIB}/{target['name']}"


def doc_path_of(doc_id: str, node: dict) -> str:
    con = db.connect()
    try:
        r = con.execute("SELECT title,folder FROM docs WHERE id=?", (doc_id,)).fetchone()
    finally:
        con.close()
    return "/" + "/".join(x for x in (node["pname"], r["folder"], r["title"]) if x) if r else ""


def _move_doc(ctx: Ctx, node: dict, dest: dict) -> None:
    from backend.routers.docs import rename_doc
    from backend.routers.project_folders import DocFolder, move_document
    from backend.schemas import TitleSet

    req = fake_request(ctx.user)
    if dest["title"] != node["title"]:
        rename_doc(node["doc_id"], TitleSet(title=dest["title"]), req, ctx.user)
    if dest["folder"] != node["folder"]:
        move_document(node["project_id"], node["doc_id"], DocFolder(folder=dest["folder"]), req, ctx.user)


def _module_version(node: dict) -> str:
    con = db.connect()
    try:
        return con.execute("SELECT updated_at FROM project_resources WHERE project_id=? AND name=?", (node["project_id"], node["name"])).fetchone()[0]
    finally:
        con.close()


def _rename_entry(ctx: Ctx, node: dict, dest: dict) -> None:
    from backend.routers.projects import EntryRename, rename_entry

    if node["kind"] == "file":
        body = EntryRename(name=node["name"], target=dest["name"], doc_id=node["doc_id"], version=hashlib.sha256(read_bytes(node)).hexdigest())
    else:
        body = EntryRename(name=node["name"], target=dest["name"], version=_module_version(node))
    rename_entry(node["project_id"], body, fake_request(ctx.user), ctx.user)


async def replace_text(ctx: Ctx, target: dict, new: str) -> None:
    """Overwrite a text that ref_edits rewrote (documents live, the rest through the save routes)."""
    if target["kind"] == "doc":
        await set_doc(ctx, target["doc_id"], lambda old: new)
    else:
        _save_text(ctx, target, new)


def _restore(ctx: Ctx, node: dict) -> dict:
    entry = node["id"]
    con = db.connect()
    try:
        doc = con.execute("SELECT id FROM docs WHERE id=? AND owner=? AND trashed=1", (entry, ctx.user)).fetchone()
    finally:
        con.close()
    if doc:
        from backend.routers.docs import restore_doc
        restore_doc(entry, fake_request(ctx.user), ctx.user)
        con = db.connect()
        try:
            r = con.execute("SELECT d.title,d.folder,p.title AS pt FROM docs d JOIN projects p ON p.id=d.project_id WHERE d.id=?", (entry,)).fetchone()
        finally:
            con.close()
        where = "/" + "/".join(x for x in (r["pt"], r["folder"], r["title"]) if x) if r else ""
        return {"restored": entry, "path": where, "note": "restored to its original place; `to` is ignored"}
    return {"restored": entry, "note": "restored to its original place; `to` is ignored", **trash.restore(ctx.user, entry)}


async def delete(ctx: Ctx, path: str, package: str = "") -> dict:
    from backend.routers import projects as rp
    from backend.routers import templates as rt
    from backend.routers.change_packages import delete_package
    from backend.routers.docs import trash_doc
    from backend.routers.files import delete_file
    from backend.routers.project_folders import delete_folder

    node = resolve(ctx, path, create=path.endswith("/") and path != "/")
    kind, req = node["kind"], fake_request(ctx.user)
    if kind == "proposal":
        delete_package(node["project_id"], node["id"], req, ctx.user)
        return {"deleted": node["path"], "note": "proposals are removed for good"}
    if kind == "new_folder":
        raise err(404, "not_found", f"No folder {node['path']!r}")
    if kind == "folder":
        need_write(node)
        delete_folder(node["project_id"], node["folder"], req, ctx.user)
    elif kind in ("doc", "file", "module") and _proposing(ctx, node):
        return await propose(ctx, node, {"op": "delete", "path": path}, package)
    elif kind == "template":
        rt.delete_template(node["name"], req, ctx.user)
    elif kind == "project":
        if node["role"] != "owner":
            raise err(403, "forbidden", "Deleting a project is for people in the web app, not for keys", hint="delete its documents instead")
        await rp.trash_project_documents(node["project_id"], req, ctx.user)
    elif kind == "doc":
        need_write(node)
        await trash_doc(node["doc_id"], req, ctx.user)
    elif kind == "file":
        need_write(node)
        delete_file(node["doc_id"], node["name"], req, ctx.user)
    elif kind == "module":
        need_write(node)
        rp.delete_resource(node["project_id"], node["name"], _module_version(node), req, ctx.user)
    else:
        raise err(400, "bad_path", f"{node['path']} cannot be deleted")
    return {"deleted": node["path"], "recover": f"/{TRASH}"}


# --- search -----------------------------------------------------------------------------------

def _hit(text: str, q: str) -> tuple[int, str]:
    i = text.lower().find(q.lower())
    if i < 0:
        return 0, ""
    return text[:i].count("\n") + 1, text.split("\n")[text[:i].count("\n")].strip()[:160]


def find(ctx: Ctx, query: str, path: str = "/", kind: str = "") -> dict:
    q = search.normalize_query(query)
    if len(q) < search.MIN_Q:
        raise err(400, "bad_request", "Search needs at least 2 characters")
    if kind and kind not in ("doc", "file", "module", "template", "trash"):
        raise err(400, "bad_request", "kind is one of doc, file, module, template, trash")
    if path.strip("/"):
        resolve(ctx, path, create=path.endswith("/"))
    con = db.connect()
    try:
        files_dir = deps.get_files_dir()
        entries = search.content_visible(ctx.user, q, con, files_dir, sync.room_text)
        named = search.search_visible(ctx.user, q, con, files_dir, sync.room_text)
        names = {p["id"]: p["name"] for p in visible_projects(con, ctx.user)}
        docs = {r["id"]: r for r in con.execute("SELECT id,title,folder,project_id FROM docs")}

        def doc_path(doc_id: str) -> str:
            d = docs.get(doc_id)
            if not d or d["project_id"] not in names:
                return ""
            return "/" + "/".join(x for x in (names[d["project_id"]], d["folder"], d["title"]) if x)

        hits, seen = [], set()
        for e in entries:
            k = e["kind"]
            if k == "doc":
                p, text = doc_path(e["doc_id"]), doc_text(e["doc_id"])
            elif k == "file":
                d = doc_path(e["doc_id"])
                p, text = (d + "/" + e["name"]) if d else "", store.get(e["doc_id"], e["name"]).decode("utf-8", errors="replace")
            elif k == "resource":
                p = f"/{names.get(e['project_id'], '')}/{LIB}/{e['name']}"
                row = con.execute("SELECT content FROM project_resources WHERE project_id=? AND name=?", (e["project_id"], e["name"])).fetchone()
                text, k = (row[0] if row else ""), "module"
            elif k == "template":
                p = f"/{TPL}/{e['name']}"
                row = con.execute("SELECT content FROM templates WHERE owner=? AND name=?", (ctx.user, e["name"])).fetchone()
                text = row[0] if row else ""
            else:
                p, text, k = f"/{TRASH}/{e.get('doc_id') or e.get('id')}", "", "trash"
            if not p:
                continue
            line, snippet = _hit(text, q)
            seen.add(p)
            hits.append({"path": p, "kind": "doc" if k == "trash_doc" else k, "count": e["count"], "line": line, "snippet": snippet})
        for pid, pname in names.items():
            for r in con.execute("SELECT name FROM project_resources WHERE project_id=? AND name LIKE ? ESCAPE '\\'", (pid, "%" + q.replace("%", "").replace("_", "") + "%")):
                p = f"/{pname}/{LIB}/{r['name']}"
                if p not in seen:
                    seen.add(p)
                    hits.append({"path": p, "kind": "module", "count": 0, "line": 0, "snippet": ""})
        for h in named:
            p = doc_path(h["id"])
            if p and p not in seen:
                hits.append({"path": p, "kind": "doc", "count": 0, "line": 0, "snippet": h["snippet"]})
    finally:
        con.close()
    prefix = "/" + path.strip("/") if path.strip("/") else ""
    hits = [h for h in hits if (not prefix or h["path"] == prefix or h["path"].startswith(prefix + "/")) and (not kind or h["kind"] == kind)]
    hits.sort(key=lambda h: -h["count"])
    return {"query": q, "hits": hits[:SEARCH_MAX], "total": len(hits)}
