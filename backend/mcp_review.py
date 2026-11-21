"""Agent review side: proposal packages, comments and the inbox.

Every write the caller may not make directly lands here as an operation; the server computes
base, content and per-change hunks itself, so the agent only says what it wants and a human
accepts single hunks, files or the whole package in the existing review mode.
"""
from __future__ import annotations

import asyncio
import base64
import difflib
import time

from fastapi import HTTPException

from backend import db
from backend.mcp_fs import Ctx, apply_edits, doc_text, err, fake_request, is_text, resolve, version
from backend.services import change_packages as cp
from backend.services import notifications, projects

CLIP = 300  # characters of a change shown when reading a package
INBOX_MAX = 50
WAIT_MAX = 25.0


def hunks(base: str, new: str) -> list[dict]:
    """Changes turning base into new: line diff, each old text widened until it occurs exactly once."""
    a, b = base.splitlines(True), new.splitlines(True)
    ops = [o for o in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if o[0] != "equal"]
    spans = []
    for _, i1, i2, j1, j2 in ops:
        lo, hi = i1, i2
        while True:
            old = "".join(a[lo:hi])
            if (old and base.count(old) == 1) or (lo == 0 and hi == len(a)):
                break
            lo, hi = max(0, lo - 1), min(len(a), hi + 1)
        spans.append([lo, hi, [(i1, i2, j1, j2)]])
    merged: list[list] = []
    for s in spans:
        if merged and s[0] < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], s[1])
            merged[-1][2] += s[2]
        else:
            merged.append(s)
    out = []
    for lo, hi, parts in merged:
        lo = min(lo, parts[0][0])
        hi = max(hi, parts[-1][1])
        new_text, at = "", lo
        for i1, i2, j1, j2 in parts:
            new_text += "".join(a[at:i1]) + "".join(b[j1:j2])
            at = i2
        new_text += "".join(a[at:hi])
        out.append({"old_string": "".join(a[lo:hi]), "new_string": new_text})
    return out


def _stub(node: dict) -> dict:
    kind = {"doc": "document", "file": "file", "module": "resource"}.get(node["kind"])
    if not kind:
        raise err(400, "bad_path", f"{node['path']} cannot be part of a proposal")
    return {"kind": kind, "doc_id": node.get("doc_id", ""), "path": "" if kind == "document" else node["name"]}


def _b64(data: str | bytes) -> str:
    return base64.b64encode(data.encode() if isinstance(data, str) else data).decode()


def _original(con, pid: str, stub: dict, binary: bool) -> str | None:
    return cp.snapshot(con, pid, {**stub, "action": "modify", "binary": binary})


def _modify(con, pid: str, files: dict, stub: dict, new: str | bytes, binary: bool) -> None:
    k = cp.key(stub)
    cur = files.get(k)
    if cur and cur["action"] == "delete":
        raise err(409, "conflict", "This file is deleted in the same package")
    if cur and cur["action"] == "add":
        cur["content"] = _b64(new) if binary else new
        return
    base = (cur["base"] if cur else _original(con, pid, stub, binary)) or ""
    content = _b64(new) if binary else str(new)
    if content == base:
        files.pop(k, None)
        return
    file: dict = {**stub, "action": "modify", "base": base, "content": content, "binary": binary}
    if not binary:
        file["changes"] = hunks(base, content)
    if cur:
        file["id"] = cur.get("id", "")
        if cur["action"] == "rename":
            file.update(action="rename", target=cur["target"], original_title=cur.get("original_title", ""), folder=cur.get("folder"))
    files[k] = {x: y for x, y in file.items() if y not in (None, "")} | ({"binary": True} if binary else {})


def _working(con, pid: str, files: dict, stub: dict) -> str:
    cur = files.get(cp.key(stub))
    if cur and cur["action"] in ("add", "modify", "rename") and not cur.get("binary"):
        return cur["content"]
    return _original(con, pid, stub, False) or ""


def _apply_op(con, ctx: Ctx, pid: str, op: dict, files: dict) -> None:
    kind = op["op"]
    if kind == "replace":  # rewritten reference from a move
        t = op["target"]
        node = {"kind": t["kind"], "doc_id": t.get("doc_id", ""), "name": t.get("name", ""), "path": t.get("path", t.get("name", ""))}
        _modify(con, pid, files, _stub(node), op["new"], False)
        return
    node = resolve(ctx, op["path"], create=kind == "write")
    if node.get("project_id") != pid:
        raise err(400, "bad_path", f"{op['path']} is not in this project", hint="every op path starts with the project path")
    if kind == "write":
        _write_op(con, pid, op, node, files)
    elif kind == "edit":
        stub = _stub(node)
        new, _ = apply_edits(_working(con, pid, files, stub), op["edits"])
        _modify(con, pid, files, stub, new, False)
    elif kind == "delete":
        stub = _stub(node)
        cur = files.get(cp.key(stub))
        if cur and cur["action"] == "add":
            files.pop(cp.key(stub))
            return
        binary = node["kind"] == "file" and not is_text(node["name"])
        base = cur["base"] if cur and cur.get("base") is not None else _original(con, pid, stub, binary)
        files[cp.key(stub)] = {**stub, "action": "delete", "base": base, **({"binary": True} if binary else {})}
    elif kind == "move":
        dest = resolve(ctx, op["to"], create=True)
        stub = _stub(node)
        binary = node["kind"] == "file" and not is_text(node["name"])
        cur = files.get(cp.key(stub))
        if node["kind"] == "doc":
            title, folder = dest["title"], dest["folder"]
            extra = {"target": title, "original_title": node["title"], "folder": folder}
        else:
            extra = {"target": dest["name"]}
        base = cur["base"] if cur and cur.get("base") is not None else _original(con, pid, stub, binary)
        content = cur["content"] if cur and cur.get("content") is not None else base
        file = {**stub, "action": "rename", "base": base, "content": content, **extra, **({"binary": True} if binary else {})}
        if cur and cur.get("changes"):
            file["changes"] = cur["changes"]
        files[cp.key(stub)] = file
    else:
        raise err(400, "bad_request", f"Unknown operation {kind!r}", hint="write, edit, move or delete")


def _write_op(con, pid: str, op: dict, node: dict, files: dict) -> None:
    data, as_text = op["data"] or b"", op["text"]
    kind = node["kind"]
    if kind == "new_doc":
        for f in files.values():
            if f["kind"] == "document" and f["action"] == "add" and f["target"] == node["title"] and f.get("folder", "") == node["folder"]:
                f["content"] = data.decode("utf-8", errors="replace")
                return
        did = db.new_id("d_")
        files[("document", did, "")] = {"kind": "document", "doc_id": did, "path": "", "action": "add", "target": node["title"],
                                        "folder": node["folder"], "content": data.decode("utf-8", errors="replace")}
        return
    binary = kind in ("file", "new_file") and not (as_text and is_text(node["name"]))
    if kind.startswith("new_"):
        stub = {"kind": "file" if kind == "new_file" else "resource", "doc_id": node.get("doc_id", ""), "path": node["name"]}
        content = _b64(data) if binary else data.decode("utf-8", errors="replace")
        files[cp.key(stub)] = {**stub, "action": "add", "content": content, **({"binary": True} if binary else {})}
        return
    stub = _stub(node)
    current = _working(con, pid, files, stub) if not binary else None
    if op.get("base_version") and current is not None and op["base_version"] != version(current):
        raise err(409, "stale_version", "The text changed since you read it", version=version(current), hint="read it again")
    _modify(con, pid, files, stub, data if binary else data.decode("utf-8", errors="replace"), binary)


async def propose(ctx: Ctx, project_id: str, ops: list[dict], title: str = "", package: str = "") -> dict:
    return await asyncio.to_thread(_propose, ctx, project_id, ops, title, package)


def _propose(ctx: Ctx, project_id: str, ops: list[dict], title: str, package: str) -> dict:
    con = db.connect()
    try:
        try:
            projects.require(con, project_id, ctx.user)
        except HTTPException:
            raise err(403, "forbidden", "Only project members can propose; ask the owner to add you") from None
        prev = cp.get(con, project_id, package) if package else None
        files = {cp.key(f): f for f in (prev["files"] if prev else [])}
        for op in ops:
            _apply_op(con, ctx, project_id, op, files)
    finally:
        con.close()
    if not files and not prev:
        raise err(400, "bad_request", "Nothing to propose: the change equals the current text")
    title = (title or (prev["title"] if prev else "") or (f"{len(ops)} changes by {ctx.author}" if ctx.author and len(ops) > 1 else
                                                          f"Changes by {ctx.author or 'agent'}"))[:100]
    saved = cp.save(ctx.user, project_id, title, list(files.values()), package, prev["revision"] if prev else 0, ctx.author)
    return {"proposal": saved["id"], "revision": saved["revision"], "title": saved["title"], "files": len(saved["files"]),
            "changes": sum(max(len(f.get("changes", [])), 1) for f in saved["files"]),
            "next": "A project editor reviews and accepts it in the UI; add more to it with package=" + saved["id"]}


# --- reading ----------------------------------------------------------------------------------

def _doc_paths(con, project_id: str) -> dict[str, str]:
    return {r["id"]: "/".join(x for x in (r["folder"], r["title"]) if x)
            for r in con.execute("SELECT id,title,folder FROM docs WHERE project_id=?", (project_id,))}


def read_proposal(ctx: Ctx, node: dict):
    from backend.routers.change_packages import read_package

    pkg = read_package(node["project_id"], node["id"], ctx.user)
    con = db.connect()
    try:
        docs = _doc_paths(con, node["project_id"])
    finally:
        con.close()
    files = []
    for f in pkg["files"]:
        where = docs.get(f.get("doc_id", ""), "")
        name = f["path"] or f.get("target", "")
        entry = {"action": f["action"], "kind": f["kind"],
                 "path": f"/{node['pname']}/" + (where if f["kind"] == "document" else f"{LIB_DIR}/{f['path']}" if f["kind"] == "resource" else f"{where}/{f['path']}")}
        if f["kind"] == "document" and f["action"] in ("add", "rename"):
            entry["path"] = f"/{node['pname']}/" + "/".join(x for x in (f.get("folder"), f.get("target")) if x)
        if f["action"] == "rename" and f["kind"] != "document":
            entry["to"] = f["target"]
        if f.get("changes"):
            entry["changes"] = [{"id": c["id"], "old": c["old_string"][:CLIP], "new": c["new_string"][:CLIP]} for c in f["changes"]]
        if name and f["action"] == "add" and f["kind"] != "document":
            entry["size"] = len(f.get("content") or "")
        files.append(entry)
    return {"path": node["path"], "title": pkg["title"], "by": pkg["author_name"] or pkg["author"], "revision": pkg["revision"],
            "accepted_changes": pkg["accepted"], "files": files}, None


LIB_DIR = ".library"


def list_proposals(ctx: Ctx, node: dict) -> dict:
    from backend.routers.change_packages import list_packages

    rows = list_packages(node["project_id"], ctx.user)["packages"]
    return {"path": node["path"], "entries": [
        {"path": f"{node['path']}/{r['id']}", "kind": "proposal", "title": r["title"], "by": r["author_name"] or r["author"],
         "files": r["file_count"], "changes": r["change_count"], "revision": r["revision"], "updated_at": r["updated_at"]} for r in rows]}


# --- comments ---------------------------------------------------------------------------------

def comment(ctx: Ctx, path: str, text: str = "", quote: str = "", line: int = 0, reply_to: str = "",
            id: str = "", resolved: bool | None = None, delete: bool = False) -> dict:
    from backend.routers import comments as rc
    from backend.schemas import ResolveSet

    node = resolve(ctx, path)
    if node["kind"] != "doc":
        raise err(400, "bad_path", "Comments live on documents")
    req = fake_request(ctx.user)
    if delete or resolved is not None:
        if not id:
            raise err(400, "bad_request", "id of the comment is required (read the document to see them)")
        if delete:
            return rc.delete_comment(node["doc_id"], id, req, ctx.user)
        return rc.resolve_comment(node["doc_id"], id, ResolveSet(resolved=bool(resolved)), req, ctx.user)
    if not text.strip() or len(text) > 2000:
        raise err(400, "bad_request", "Comment text: 1-2000 characters")
    if id:
        raise err(400, "bad_request", "id is for resolved=true/false or delete=true; reply with reply_to=<thread id>")
    anchor = line
    doc = doc_text(node["doc_id"])
    if quote:
        if quote not in doc:
            raise err(400, "bad_request", "quote is not in the document", hint="copy it from read, or use line")
        anchor = doc[:doc.find(quote)].count("\n") + 1 if not line else line
    if line > len(doc.split("\n")):
        raise err(400, "bad_request", f"line {line} is past the end ({len(doc.splitlines())} lines)")
    cid, ref = db.new_id("c_"), None
    con = db.connect()
    try:
        if reply_to:
            p = con.execute("SELECT parent_id FROM comments WHERE id=? AND doc_id=?", (reply_to, node["doc_id"])).fetchone()
            if not p:
                raise err(404, "not_found", "That thread is gone")
            if p["parent_id"]:
                raise err(400, "bad_request", "Reply to the first comment of a thread")
        con.execute("INSERT INTO comments (id,doc_id,username,author,anchor,quote,text,parent_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (cid, node["doc_id"], ctx.user, ctx.author[:40], max(1, anchor), quote[:500], text.strip(), reply_to or None, db.now_iso()))
        con.commit()
        ref = reply_to or cid
    finally:
        con.close()
    notifications.notify_mentions(node["doc_id"], ctx.user, text, ref)
    return {"id": cid, "line": max(1, anchor)}


# --- inbox ------------------------------------------------------------------------------------

def _unread(ctx: Ctx, since: str) -> list[dict]:
    con = db.connect()
    try:
        rows = con.execute("SELECT id,type,doc_id,text,project_id,ref,actor,created_at FROM notifications "
                           "WHERE recipient=? AND is_read=0 AND created_at>? ORDER BY created_at LIMIT ?",
                           (ctx.user, since, INBOX_MAX * 4)).fetchall()
        out = []
        for r in rows:
            mine = ctx.author and f"@{ctx.author.lower()}" in (r["text"] or "").lower()
            if r["type"] == "mention" and not mine:
                continue
            if r["type"] not in ("mention", "reviewed"):
                continue
            where = _where(con, r["doc_id"], r["project_id"])
            out.append({"id": r["id"], "type": r["type"], "text": r["text"], "path": where, "ref": r["ref"], "by": r["actor"], "at": r["created_at"]})
        return out[:INBOX_MAX]
    finally:
        con.close()


def _where(con, doc_id: str, project_id: str) -> str:
    row = con.execute("SELECT d.title,d.folder,p.title AS pt,p.owner,p.id AS pid FROM docs d JOIN projects p ON p.id=d.project_id WHERE d.id=?", (doc_id,)).fetchone() if doc_id else None
    if row:
        return "/" + "/".join(x for x in (f"{row['pt']}" if True else "", row["folder"], row["title"]) if x)
    p = con.execute("SELECT title FROM projects WHERE id=?", (project_id,)).fetchone() if project_id else None
    return f"/{p['title']}/.proposals" if p else ""


async def inbox(ctx: Ctx, since: str = "", wait: float = 0, ack: list[str] | None = None) -> dict:
    for nid in ack or []:
        await asyncio.to_thread(notifications.mark_read, nid, ctx.user)
    end = time.monotonic() + min(max(wait, 0), WAIT_MAX)
    while True:
        items = await asyncio.to_thread(_unread, ctx, since)
        if items or time.monotonic() >= end:
            return {"items": items, "since": items[-1]["at"] if items else since,
                    "hint": "Pass ack=[ids] once handled; since=<since> to poll for newer items."}
        await asyncio.sleep(1)
