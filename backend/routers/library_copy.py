"""Explicit document-file copies into a personal or project library."""
from __future__ import annotations

import hashlib
import json
import posixpath
from collections import Counter
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend import db, deps
from backend.constants import MAX_TXT
from backend.services import projects, quota, resources
from backend.services.docfiles import need_text, store
from backend.services.sidebar import notify_sidebar

router = APIRouter()


class Pull(BaseModel):
    source_scope: str
    source_project_id: str = ""
    source: str = Field(min_length=1, max_length=240)
    scope: str
    project_id: str = ""
    name: str = Field(min_length=1, max_length=240)
    folder: str = Field(default="", max_length=40)
    renames: dict[str, str] = Field(default_factory=dict)
    preview: str = ""


def source_library(con, user: str, b: Pull) -> dict[str, str]:
    if b.source_scope == "personal":
        return {r["name"]: r["content"] for r in con.execute("SELECT name,content FROM templates WHERE owner=?", (user,))}
    if b.source_scope != "project":
        raise HTTPException(400, "Choose a personal or project source")
    try:
        projects.require(con, b.source_project_id, user)
    except HTTPException as e:
        if e.status_code != 404:
            raise
        # A document guest may pull only sources already visible through that document.
        visible: dict[str, str] = {}
        for d in con.execute("SELECT id,owner,content FROM docs WHERE project_id=? AND trashed=0", (b.source_project_id,)).fetchall():
            if not db.role_on(con, user, d["id"]):
                continue
            local = {f.path: store.get(d["id"], f.path).decode("utf-8", errors="replace")
                     for f in store.list(d["id"]) if resources.kind_of(f.path)}
            visible.update(resources.doc_effective(d["owner"], d["content"], local, d["id"])["resources"])
        return visible
    return {r["name"]: r["content"] for r in con.execute("SELECT name,content FROM project_resources WHERE project_id=?", (b.source_project_id,))}


def inspect_pull(con, user: str, b: Pull) -> dict:
    from backend.routers.projects import resource_name

    source = resource_name(b.source)
    shelf = source_library(con, user, b)
    if source not in shelf:
        raise HTTPException(404, "Source module not found")
    if b.scope == "personal":
        owner = user
        existing = {r["name"]: r["updated_at"] for r in con.execute("SELECT name,updated_at FROM templates WHERE owner=?", (user,))}
    elif b.scope == "project":
        if b.folder:
            raise HTTPException(400, "Include the target folder in the module path")
        projects.require(con, b.project_id, user, edit=True)
        owner = con.execute("SELECT owner FROM projects WHERE id=?", (b.project_id,)).fetchone()[0]
        existing = {r["name"]: r["updated_at"] for r in con.execute("SELECT name,updated_at FROM project_resources WHERE project_id=?", (b.project_id,))}
    else:
        raise HTTPException(400, "Choose a personal or project target")
    root = resource_name(b.name)
    if PurePosixPath(root).suffix.lower() != PurePosixPath(source).suffix.lower():
        raise HTTPException(400, "Keep the source file extension")
    queue = [source]
    found: dict[str, str] = {}
    while queue:
        n = queue.pop(0)
        if n in found:
            continue
        if len(found) >= resources.REACHABLE_MAX:
            raise HTTPException(413, "Too many module dependencies")
        found[n] = shelf[n]
        if n.lower().endswith(".typ"):
            for ref in resources.refs_in_text(shelf[n]):
                resolved = resources._resolve_ref(n, ref, {}, shelf)
                if resolved and resolved not in found:
                    queue.append(resolved)
    names = {source: root}
    for n in found:
        if n == source:
            continue
        relative = posixpath.relpath(n, posixpath.dirname(source) or ".")
        mapped = posixpath.normpath(posixpath.join(posixpath.dirname(root), relative))
        if mapped.startswith("../") or mapped == "..":
            mapped = n
        names[n] = resource_name(b.renames.get(n, posixpath.basename(n) if b.scope == "personal" else mapped))
    if any(PurePosixPath(names[n]).suffix.lower() != PurePosixPath(n).suffix.lower() for n in names):
        raise HTTPException(400, "Keep dependency file extensions")
    if b.scope == "personal" and any("/" in n or len(n) > 100 or resources.res_name(n) != n for n in names.values()):
        raise HTTPException(400, "Personal modules need filenames; choose a separate collection folder")
    duplicate_names = {n for n, count in Counter(names.values()).items() if count > 1}
    copies = {}
    for old, content in found.items():
        def rewrite(match, old=old):
            resolved = resources._resolve_ref(old, match.group(1), {}, shelf)
            if resolved not in names:
                return match.group(0)
            target = names[resolved]
            ref = "/" + target if match.group(1).startswith("/") else posixpath.relpath(target, posixpath.dirname(names[old]) or ".")
            return json.dumps(ref)
        copies[names[old]] = resources.REF_RE.sub(rewrite, content) if old.lower().endswith(".typ") else content
        if len(copies[names[old]].encode("utf-8")) > MAX_TXT:
            raise HTTPException(413, "Text resource exceeds 200 KB")
    # #7: case-variant module names ('Layout.typ' vs 'layout.typ') would show
    # as two rows, so the collision set folds case.
    existing_lower = {n.lower() for n in existing}
    collisions = sorted(
        (set(copies) & existing.keys()) | duplicate_names
        | {n for n in copies if n.lower() in existing_lower}
    )
    fingerprint = [b.model_dump(exclude={"preview"}), copies, {n: existing.get(n) for n in copies}]
    return {"owner": owner, "content": copies, "name": root,
            "files": [{"source": n, "name": names[n]} for n in found],
            "dependencies": [names[n] for n in found if n != source], "collisions": collisions,
            "warnings": ["Only static text dependencies can be pulled. Check dynamic paths and binary assets manually."],
            "preview": hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()}


@router.post("/api/library/pull-preview")
def pull_preview(b: Pull, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        p = inspect_pull(con, user, b)
        return {k: v for k, v in p.items() if k not in ("content", "owner")}
    finally:
        con.close()


@router.post("/api/library/pull")
def pull_module(b: Pull, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "templates")
    with db.tx() as con:
        p = inspect_pull(con, user, b)
        if p["collisions"]:
            raise HTTPException(409, "Name already exists; choose another target name")
        if b.preview != p["preview"]:
            raise HTTPException(409, "Source or target changed; review the pull again")
        quota.check_quota(p["owner"], sum(len(c.encode("utf-8")) for c in p["content"].values()), con)
        now = db.now_iso()
        for name, content in p["content"].items():
            if b.scope == "personal":
                con.execute("INSERT INTO templates(owner,name,content,line,folder,updated_at) VALUES (?,?,?,?,?,?)",
                            (user, name, content, resources.insert_line(name), b.folder, now))
            else:
                con.execute("INSERT INTO project_resources VALUES (?,?,?,?)", (b.project_id, name, content, now))
        if b.scope == "personal":
            deps.ensure_folder(con, user, "tpl", b.folder)
    quota.invalidate_quota_cache(p["owner"])
    if b.scope == "project":
        projects.notify(b.project_id)
    else:
        notify_sidebar(user)
    return {"name": p["name"], "version": now, "files": p["files"]}


class Copy(BaseModel):
    source: str = Field(min_length=1, max_length=240)
    scope: str
    project_id: str = ""
    name: str = Field(min_length=1, max_length=240)
    folder: str = Field(default="", max_length=40)
    preview: str = ""


def inspect_copy(con, user: str, doc_id: str, b: Copy) -> dict:
    from backend.routers.projects import resource_name

    deps._tx_role(con, user, doc_id)  # Reading the source is sufficient; target permissions are checked below.
    source = need_text(b.source)
    try:
        content = store.get(doc_id, source).decode("utf-8")
    except FileNotFoundError:
        raise HTTPException(404, "Source file gone") from None
    except UnicodeDecodeError:
        raise HTTPException(400, "Source must be UTF-8 text") from None
    if len(content.encode("utf-8")) > MAX_TXT:
        raise HTTPException(413, "Text resource exceeds 200 KB")
    name = resource_name(b.name)
    if PurePosixPath(name).suffix.lower() != PurePosixPath(source).suffix.lower():
        raise HTTPException(400, "Keep the source file extension")
    resource_clash = False  # case-variant module names would render as two rows (#7)
    if b.scope == "personal":
        if "/" in name or len(name) > 100 or resources.res_name(name) != name:
            raise HTTPException(400, "Personal library: choose a filename and a separate library folder")
        target = con.execute("SELECT updated_at FROM templates WHERE owner=? AND name=?", (user, name)).fetchone()
        owner = user
    elif b.scope == "project":
        if b.folder:
            raise HTTPException(400, "For project libraries, include the folder in the target name")
        projects.require(con, b.project_id, user, edit=True)
        target = con.execute("SELECT updated_at FROM project_resources WHERE project_id=? AND name=?", (b.project_id, name)).fetchone()
        owner = con.execute("SELECT owner FROM projects WHERE id=?", (b.project_id,)).fetchone()[0]
        resource_clash = name.lower() in {r["name"].lower() for r in con.execute(
            "SELECT name FROM project_resources WHERE project_id=?",
            (b.project_id,),
        ).fetchall()}
    else:
        raise HTTPException(400, "Choose personal or project library")
    dependencies = resources.refs_in_text(content) if source.lower().endswith(".typ") else []
    warnings = []
    if dependencies:
        warnings.append("Dependencies are not copied. Relative references stay unchanged; ensure the target library contains them at the required paths.")
    if source.lower().endswith(".typ"):
        warnings.append("Dynamic references and binary dependencies cannot be completely detected.")
    fingerprint = [source, content, b.scope, b.project_id, name, b.folder, list(target) if target else None]
    collisions: list[str] = []
    if target or resource_clash:
        collisions.append(name)
    return {"name": name, "content": content, "owner": owner, "dependencies": dependencies,
            "warnings": warnings, "collisions": collisions,
            "preview": hashlib.sha256(json.dumps(fingerprint).encode()).hexdigest()}


@router.post("/api/docs/{doc_id}/library-copy-preview")
def copy_preview(doc_id: str, b: Copy, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "files_list")
    con = db.connect()
    try:
        p = inspect_copy(con, user, doc_id, b)
        return {k: v for k, v in p.items() if k not in ("content", "owner")}
    finally:
        con.close()


@router.post("/api/docs/{doc_id}/library-copy")
def copy_file(doc_id: str, b: Copy, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "templates")
    with db.tx() as con:
        p = inspect_copy(con, user, doc_id, b)
        if p["collisions"]:
            raise HTTPException(409, "Name already exists; choose another name")
        if b.preview != p["preview"]:
            raise HTTPException(409, "Source or target changed; review the copy again")
        quota.check_quota(p["owner"], len(p["content"].encode("utf-8")), con)
        now = db.now_iso()
        if b.scope == "personal":
            con.execute("INSERT INTO templates(owner,name,content,line,folder,updated_at) VALUES (?,?,?,?,?,?)",
                        (user, p["name"], p["content"], resources.insert_line(p["name"]), b.folder, now))
            deps.ensure_folder(con, user, "tpl", b.folder)
        else:
            con.execute("INSERT INTO project_resources VALUES (?,?,?,?)", (b.project_id, p["name"], p["content"], now))
    quota.invalidate_quota_cache(p["owner"])
    if b.scope == "project":
        projects.notify(b.project_id)
    else:
        notify_sidebar(user)
    return {"name": p["name"], "version": now}
