"""Project proposals: stored drafts, versioned corrections and atomic partial acceptance."""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import posixpath
import re
import sqlite3
import time
from contextlib import ExitStack

from fastapi import HTTPException
from pycrdt import Doc, Text

from backend import config, db, deps, sync
from backend.constants import MAX_TXT, TITLE_MAX
from backend.services import projects, quota, resources, trash
from backend.services.docfiles import file_type, safe_name, store
from backend.services.locks import _named_lock

log = logging.getLogger("typst.main")


def encode(files: list[dict]) -> str:
    return json.dumps(files, ensure_ascii=False, separators=(",", ":"))


def data_size(value: str | None, binary: bool) -> int:
    return len(base64.b64decode(value)) if binary and value is not None else len((value or "").encode())


def key(file: dict) -> tuple[str, str, str]:
    return file["kind"], file.get("doc_id", ""), file["path"]


def snapshot(con, project: str, file: dict) -> str | None:
    kind, document, path = key(file)
    if kind not in ("document", "resource", "file"):
        raise HTTPException(400, "Invalid proposal file kind")
    if kind == "document":
        row = con.execute(
            "SELECT content FROM docs WHERE id=? AND project_id=? AND trashed=0", (document, project)
        ).fetchone()
        if not row:
            if file["action"] == "add" and not con.execute("SELECT 1 FROM docs WHERE id=?", (document,)).fetchone():
                return None
            raise HTTPException(404, "Document gone")
        live = sync.room_text(document)
        return live if live is not None else row[0]
    safe_name(path)
    if kind == "resource":
        from backend.routers.projects import resource_name

        resource_name(path)
        row = con.execute(
            "SELECT content FROM project_resources WHERE project_id=? AND name=?", (project, path)
        ).fetchone()
        return row[0] if row else None
    if path == "main.typ":
        raise HTTPException(400, "Use document scope for main.typ")
    if not con.execute("SELECT 1 FROM docs WHERE id=? AND project_id=? AND trashed=0", (document, project)).fetchone():
        raise HTTPException(404, "Source document gone")
    try:
        data = store.get(document, path)
    except FileNotFoundError:
        return None
    try:
        return base64.b64encode(data).decode() if file.get("binary") else data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(400, "Use a binary proposal for this attachment") from error


def apply_changes(text: str, changes: list[dict]) -> str:
    spans: list[tuple[int, int, str]] = []
    for change in changes:
        old, new = change["old_string"], change["new_string"]
        count = text.count(old)
        if old == new or count != 1:
            # Occurrence hint for whatever stays hard-failing (draft
            # validation, whole-package accept): 0 usually means the
            # passage was already applied or removed meanwhile.
            raise HTTPException(409, f"Original passage changed or is ambiguous ({count} occurrences found)")
        at = text.index(old)
        if any(at < end and at + len(old) > start or at == start for start, end, _ in spans):
            raise HTTPException(400, "Overlapping proposal changes")
        spans.append((at, at + len(old), new))
    for start, end, new in sorted(spans, reverse=True):
        text = text[:start] + new + text[end:]
    return text


def validate_file(file: dict) -> None:
    if file["kind"] in ("document", "file"):
        deps.check_doc_id(file.get("doc_id", ""))
    if file["kind"] == "document" and file["path"] != "main.typ":
        raise HTTPException(400, "Document scope must use main.typ")
    if file["kind"] == "resource" and file.get("doc_id"):
        raise HTTPException(400, "Project resources have no document scope")
    if file["action"] not in ("modify", "add", "delete", "rename"):
        raise HTTPException(400, "Invalid file action")
    if file["kind"] == "document" and file["action"] in ("add", "rename"):
        title = file.get("target", "")
        if not title.strip() or title != title.strip() or len(title) > TITLE_MAX or "/" in title:
            raise HTTPException(400, "Invalid proposed document title")
        if file["action"] == "rename" and not file.get("original_title"):
            raise HTTPException(400, "Missing original document title")
    if file.get("binary") and file["kind"] != "file":
        raise HTTPException(400, "Only attachments may be binary")
    if file["action"] == "add" and file.get("base") is not None:
        raise HTTPException(400, "Added file already has a base")
    if file["action"] != "add" and file.get("base") is None:
        raise HTTPException(400, "Missing original file")
    for field in ("base", "content", "initial_content"):
        value = file.get(field)
        if value is not None:
            try:
                size = len(base64.b64decode(value, validate=True)) if file.get("binary") else len(value.encode())
            except ValueError as error:
                raise HTTPException(400, "Invalid binary attachment") from error
            if size > (10 * 1024 * 1024 if file.get("binary") else MAX_TXT):
                raise HTTPException(413, "Proposal file too large")
    if (file["action"] == "modify" or file["action"] == "rename" and file.get("changes")) and not file.get("binary"):
        if not file.get("changes") or apply_changes(file["base"], file["changes"]) != file.get("content"):
            raise HTTPException(400, "Changes do not match proposed content")
    if file["action"] != "delete" and file.get("content") is None:
        raise HTTPException(400, "Missing proposed content")
    if file["action"] == "rename" and file["kind"] != "document":
        safe_name(file.get("target", ""))
        if file["kind"] == "resource":
            from backend.routers.projects import resource_name

            resource_name(file["target"])


def get(con, project: str, package: str) -> dict:
    row = con.execute("SELECT * FROM suggestion_packages WHERE id=? AND project_id=?", (package, project)).fetchone()
    if not row:
        raise HTTPException(404, "Proposal package gone")
    result = dict(row)
    result["files"] = json.loads(row["files"])
    return result


def save(user: str, project: str, title: str, files: list[dict], package: str = "", revision: int = 0, author_name: str = "") -> dict:
    with _named_lock("packages:" + project):
        # Phase 1 (no write tx): snapshots, validation and serialization run
        # OUTSIDE BEGIN IMMEDIATE so a big draft cannot stall other writers;
        # the tx below holds the writer only for the short DB writes.
        con = db.connect()
        try:
            role = projects.require(con, project, user)
            owner = con.execute("SELECT owner FROM projects WHERE id=?", (project,)).fetchone()[0]
            previous = get(con, project, package) if package else None
            if previous and previous["author"] != user and role not in ("owner", "editor"):
                raise HTTPException(403, "Only the author or an editor may correct a proposal")
            if previous and previous["revision"] != revision:
                raise HTTPException(409, "Proposal changed; reopen the current version")
            identities = set()
            file_ids = set()
            for file in files:
                if file["action"] == "add" and file.get("initial_content") is None:
                    file["initial_content"] = file.get("content")
                if file["kind"] == "document" and file["action"] == "add" and not file.get("doc_id"):
                    file["doc_id"] = db.new_id("d_")
                if key(file) in identities:
                    raise HTTPException(400, "Duplicate proposal file")
                identities.add(key(file))
                validate_file(file)
                original = snapshot(con, project, file)
                if file["kind"] == "document" and file["action"] == "rename":
                    title_row = con.execute("SELECT title FROM docs WHERE id=?", (file["doc_id"],)).fetchone()
                    if title_row[0] != file["original_title"]:
                        raise HTTPException(409, "Original document title changed")
                if file["action"] == "add" and original is not None:
                    raise HTTPException(409, "Added filename already exists")
                if not previous and original != file.get("base"):
                    if file["action"] == "modify" and not file.get("binary") and original is not None:
                        # Keep independent source edits instead of making the author restart their draft.
                        for change in file["changes"]:
                            old, new = change["old_string"], change["new_string"]
                            if old in new and original.count(new) > file["base"].count(new):
                                raise HTTPException(409, "Original passage changed; insertion already applied")
                        try:
                            file["content"] = apply_changes(original, file["changes"])
                        except HTTPException as error:
                            if error.status_code == 400:
                                raise HTTPException(409, "Original passage changed; proposal passages overlap") from error
                            raise
                        file["base"] = original
                    else:
                        raise HTTPException(409, "Original file changed; refresh the draft")
                previous_file = next((old for old in previous["files"] if key(old) == key(file)), None) if previous else None
                if previous and file.get("base") != (previous_file.get("base") if previous_file else original):
                    raise HTTPException(409, "Proposal original cannot be replaced; rebase the draft")
                file.setdefault("id", db.new_id("pf_"))
                if file["id"] in file_ids:
                    raise HTTPException(400, "Duplicate proposal file id")
                file_ids.add(file["id"])
                change_ids = set()
                for change in file.get("changes", []):
                    change.setdefault("id", db.new_id("pc_"))
                    if change["id"] in change_ids:
                        raise HTTPException(400, "Duplicate proposal change id")
                    change_ids.add(change["id"])
            payload = encode(files)
            payload_size = len(payload.encode())
            if payload_size > 30 * 1024 * 1024:
                raise HTTPException(413, "Proposal package too large")
            deny = payload_size - (len(encode(previous["files"]).encode()) if previous else 0)
            quota.check_quota(owner, deny, con)
        finally:
            con.close()
        # Phase 2: short write tx (DB writes only). Re-check access on the tx
        # connection: the read phase can go stale like any pre-tx check (B5).
        with db.tx() as con2:
            role = projects.require(con2, project, user)
            if previous and previous["author"] != user and role not in ("owner", "editor"):
                raise HTTPException(403, "Only the author or an editor may correct a proposal")
            quota.check_quota(owner, deny, con2)
            now = db.now_iso()
            if previous:
                con2.execute(
                    "UPDATE suggestion_packages SET title=?,files=?,revision=revision+1,updated_at=? WHERE id=?",
                    (title, payload, now, package),
                )
            else:
                package = db.new_id("sp_")
                con2.execute(
                    "INSERT INTO suggestion_packages(id,project_id,author,author_name,title,files,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (package, project, user, author_name.strip()[:40], title, payload, now, now),
                )
            result = get(con2, project, package)
    quota.invalidate_quota_cache(owner)
    projects.notify(project)
    return result


def dependencies(con, project: str, pending: list[dict], writes: list[tuple[dict, str | None]],
                 include_related: bool = False) -> list[tuple[str, str]]:
    texts: dict[tuple[str, str, str], str] = {}
    available = set()
    deleting = {f['doc_id'] for f, _ in writes if f['kind'] == 'document' and f['action'] == 'delete'}
    for row in con.execute("SELECT id,content FROM docs WHERE project_id=? AND trashed=0", (project,)):
        if row['id'] in deleting:
            continue
        identity = ("document", row["id"], "main.typ")
        # room_text() returns "" for an emptied live room (not None) - only
        # a missing room falls back to the DB text, like snapshot().
        live = sync.room_text(row["id"])
        texts[identity] = live if live is not None else row["content"]
        available.add(identity)
        for attachment in store.list(row["id"]):
            identity = ("file", row["id"], attachment.path)
            available.add(identity)
            if resources.kind_of(attachment.path):
                try:
                    texts[identity] = store.get(row["id"], attachment.path).decode()
                except UnicodeDecodeError:
                    pass
    for row in con.execute("SELECT name,content FROM project_resources WHERE project_id=?", (project,)):
        identity = ("resource", "", row["name"])
        available.add(identity)
        texts[identity] = row["content"]
    sensitive = {key(f) for f in pending if f["action"] == "delete" or f["action"] == "rename"}
    sensitive.update((f["kind"], f.get("doc_id", ""), f.get("target", f["path"])) for f in pending if f["action"] in ("add", "rename"))
    for file, content in writes:
        if file['kind'] == 'file' and file.get('doc_id') in deleting:
            continue
        identity = key(file)
        if file["action"] in ("delete", "rename"):
            available.discard(identity)
            texts.pop(identity, None)
        if content is not None:
            target = (file["kind"], file.get("doc_id", ""), file["path"] if file["kind"] == "document" else file.get("target", file["path"]))
            available.add(target)
            if not file.get("binary"):
                texts[target] = content
    for identity, content in texts.items():
        _kind, document, path = identity
        parent = posixpath.dirname(path)
        for ref in set(resources.refs_in_text(content)) | set(re.findall(r'"([^"\n]+)"', content)):
            for resolved in {ref, posixpath.normpath(posixpath.join(parent, ref))}:
                local = ("file", document, resolved)
                shared = ("resource", "", resolved)
                if local in available or shared in available:
                    continue
                if local in sensitive or shared in sensitive:
                    if include_related:
                        for file in pending:
                            target = (file["kind"], file.get("doc_id", ""), file.get("target", file["path"]))
                            if file["action"] in ("add", "rename") and target in (local, shared):
                                return [(file["id"], "@rename" if file["action"] == "rename" else "")]
                        source = next((f for f in pending if key(f) == identity or
                                       f["action"] == "rename" and (f["kind"], f.get("doc_id", ""), f.get("target")) == identity), None)
                        if source and source["action"] in ("modify", "rename") and not source.get("binary"):
                            quoted = '"' + ref + '"'
                            changes = [(source["id"], c["id"]) for c in source["changes"]
                                       if c["old_string"].count(quoted) > c["new_string"].count(quoted)]
                            if changes:
                                return changes
                    raise HTTPException(409, {"code": "proposal_dependencies", "message": "Accept the referenced file and its text changes together: " + ref})
    return []


def csv_cell_content(base: str, proposed: str, row: int, column: int, delimiter: str) -> str:
    def values(text):
        return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))

    old, new = values(base), values(proposed)
    def value(rows):
        return rows[row][column] if row < len(rows) and column < len(rows[row]) else ""

    target = value(new)
    if value(old) == target:
        raise HTTPException(409, "Cell is no longer pending")
    encoded = io.StringIO(newline="")
    csv.writer(encoded, delimiter=delimiter, lineterminator="\r\n").writerow([target])
    replacement = encoded.getvalue()[:-2] if target else ""
    # Locate the raw cell without reserializing unrelated quoting/line endings.
    r = c = start = i = 0
    quoted = False
    bounds = None
    row_end = None
    while i <= len(base):
        ch = base[i] if i < len(base) else ""
        if ch == '"':
            if quoted and i + 1 < len(base) and base[i + 1] == '"':
                i += 2
                continue
            quoted = not quoted
        if i == len(base) or not quoted and ch in (delimiter, "\r", "\n"):
            if (r, c) == (row, column):
                bounds = (start, i)
                break
            if ch != delimiter:
                if r == row:
                    row_end = (i, c)
                    break
                r += 1
                c = 0
                if ch == "\r" and i + 1 < len(base) and base[i + 1] == "\n":
                    i += 1
            else:
                c += 1
            start = i + 1
        i += 1
    if bounds:
        content = base[:bounds[0]] + replacement + base[bounds[1]:]
    elif row_end:
        at, last = row_end
        content = base[:at] + delimiter * (column - last) + replacement + base[at:]
    else:
        content = base + ("" if not base or base.endswith(("\n", "\r")) else "\n")
        content += "\n" * max(0, row - len(old)) + delimiter * column + replacement + "\n"
    def compact(rows):
        for cells in rows:
            while cells and not cells[-1]:
                cells.pop()
        while rows and not rows[-1]:
            rows.pop()
        return rows

    return proposed if compact(values(content)) == compact(new) else content


def accept(
    user: str, project: str, package: str, revision: int, file_id: str = "", change_id: str = "", cell: dict | None = None,
    field_edit: dict | None = None, include_dependencies: bool = False
) -> tuple[dict, list, list[str]]:
    updates = []
    deleted_documents: list[str] = []
    backups: dict[tuple[str, str], bytes | None] = {}
    with ExitStack() as locks:
        locks.enter_context(_named_lock("packages:" + project))
        con = db.connect()
        try:
            projects.require(con, project, user, edit=True)
            preliminary = get(con, project, package)
        finally:
            con.close()
        documents = sorted({f["doc_id"] for f in preliminary["files"] if f.get("doc_id")})
        for document in documents:
            locks.enter_context(_named_lock("upload:" + document))
        for document in documents:
            if any(f["kind"] == "document" and f.get("doc_id") == document and f["action"] != "add" for f in preliminary["files"]):
                locks.enter_context(sync._doc_lock(sync.room(document)))
        try:
            with db.tx() as con:
                projects.require(con, project, user, edit=True)
                owner = con.execute("SELECT owner FROM projects WHERE id=?", (project,)).fetchone()[0]
                proposal = get(con, project, package)
                if proposal["revision"] != revision:
                    raise HTTPException(409, "Proposal changed; reopen the current version")
                selection: dict[str, set[str] | None] = {
                    f["id"]: ({change_id} if change_id else None)
                    for f in proposal["files"] if not file_id or f["id"] == file_id
                }
                doc_before: dict[str, str] = {}
                while True:
                    writes: list[tuple[dict, str | None]] = []
                    content: str | None
                    remaining = []
                    accepted = 0
                    stale_marked = False
                    for file in proposal["files"]:
                        if file["id"] not in selection:
                            remaining.append(file)
                            continue
                        selected_ids = selection[file["id"]]
                        structural_only = file["action"] in ("rename", "add", "delete") and selected_ids == {"@action"}
                        rename_ids = selected_ids if file["action"] == "rename" else None
                        if rename_ids is not None and file.get("binary") and not rename_ids <= {"@action", "@rename"}:
                            raise HTTPException(400, "Single-change acceptance requires a text modification")
                        if selected_ids and rename_ids is None and not structural_only and (file["action"] != "modify" or file.get("binary")):
                            raise HTTPException(400, "Single-change acceptance requires a text modification")
                        current = snapshot(con, project, file)
                        if rename_ids is not None:
                            if current != file.get("base"):
                                raise HTTPException(409, "Original file changed")
                            selected = [c for c in file.get("changes", []) if c["id"] in rename_ids]
                            if rename_ids - {"@action", "@rename"} - {c["id"] for c in selected}:
                                raise HTTPException(409, "Change is no longer pending")
                            content = apply_changes(current or "", selected) if selected else current
                            if content != file["content"]:
                                pending_content = {**file, "action": "modify", "path": file["path"] if file["kind"] == "document" else file["target"], "base": content}
                                pending_content.pop("target", None)
                                pending_content["changes"] = [c for c in file.get("changes", []) if c not in selected] or ([] if file.get("binary") else [
                                    {"id": db.new_id("pc_"), "old_string": content, "new_string": file["content"]}])
                                remaining.append(pending_content)
                            accepted += 1
                        elif structural_only and file["action"] == "add":
                            if current is not None:
                                raise HTTPException(409, "Added filename already exists")
                            content = file.get("initial_content", file["content"])
                            if content != file["content"]:
                                remaining.append({**file, "action": "modify", "base": content, "changes": [] if file.get("binary") else [
                                    {"id": db.new_id("pc_"), "old_string": content, "new_string": file["content"]}]})
                            accepted += 1
                        elif file["id"] == file_id and (cell is not None or field_edit is not None):
                            extensions = (".bib",) if field_edit else (".csv", ".tsv")
                            if file["action"] not in ("modify", "add") or file.get("binary") or not file["path"].lower().endswith(extensions):
                                raise HTTPException(400, "Selection requires a supported structured text modification")
                            if current != file.get("base"):
                                raise HTTPException(409, "Original file changed")
                            if field_edit is not None:
                                content = apply_changes(current or "", [field_edit])
                            else:
                                assert cell is not None
                                content = csv_cell_content(current or "", file["content"], cell["row"], cell["column"], "\t" if file["path"].lower().endswith(".tsv") else ",")
                            if content != file["content"]:
                                remaining.append({**file, "action": "modify", "base": content, "changes": [{"id": db.new_id("pc_"), "old_string": content, "new_string": file["content"]}]})
                            accepted += 1
                        elif file["action"] == "modify" and not file.get("binary"):
                            selected = [c for c in file["changes"] if selected_ids is None or c["id"] in selected_ids]
                            if not selected:
                                raise HTTPException(409, "Change is no longer pending")
                            if current == file.get("base") or not file_id:
                                # Exact re-match or a whole-package accept that
                                # still gives all-or-nothing: a drifted old_string
                                # hard-fails instead of silently skipping text.
                                content = apply_changes(current or "", selected)
                            else:
                                try:
                                    content = apply_changes(current or "", selected)
                                except HTTPException:
                                    # Selected change drifted out of the live text.
                                    # Same graceful path as an unrebasable sibling:
                                    # skip the file, mark it stale for the UI; the
                                    # rest of the selection still applies.
                                    remaining.append({**file, "stale": True})
                                    stale_marked = True
                                    continue
                            rest = [c for c in file["changes"] if c not in selected]
                            if rest:
                                try:
                                    rebased = apply_changes(content, rest)
                                except HTTPException:
                                    # Unselected sibling no longer matches the
                                    # post-accept text: retain only pending edits
                                    # against their original base for correction.
                                    remaining.append({**file, "changes": rest,
                                                      "content": apply_changes(file["base"], rest), "stale": True})
                                else:
                                    remaining.append(
                                        {**file, "base": content, "content": rebased, "changes": rest}
                                    )
                            accepted += len(selected)
                        else:
                            if current != file.get("base"):
                                raise HTTPException(409, "Original file changed")
                            content = None if file["action"] == "delete" else file["content"]
                            accepted += 1
                        writes.append((file, content))
                    if not writes and not stale_marked and not proposal["files"] and not file_id:
                        return proposal, [], []
                    if not writes and not stale_marked:
                        raise HTTPException(409, "No pending changes selected")
                    required = dependencies(con, project, proposal["files"], writes, include_dependencies) if writes else []
                    if not required:
                        break
                    extended = False
                    for related_file, related_change in required:
                        if related_file not in selection:
                            selection[related_file] = {related_change} if related_change else None
                            extended = True
                        elif not related_change and selection[related_file] is not None:
                            selection[related_file] = None
                            extended = True
                        elif related_change:
                            ids = selection[related_file]
                            if ids is not None and related_change not in ids:
                                ids.add(related_change)
                                extended = True
                    if not extended:
                        raise HTTPException(409, "Dependent proposal changed; refresh the package")
                deleting = {f['doc_id'] for f, _ in writes if f['kind'] == 'document' and f['action'] == 'delete'}
                if any(f['kind'] == 'file' and f.get('doc_id') in deleting for f in remaining):
                    raise HTTPException(409, "Accept document deletion and its attachment changes together")
                writes.sort(key=lambda item: item[0]['kind'] == 'document' and item[0]['action'] == 'delete')
                for document in documents:
                    names = {entry.path for entry in store.list(document)}
                    for file, content in writes:
                        if file["kind"] != "file" or file.get("doc_id") != document:
                            continue
                        if file["action"] in ("delete", "rename"):
                            names.discard(file["path"])
                        if content is not None:
                            names.add(file.get("target", file["path"]) if file["action"] == "rename" else file["path"])
                    if len(names) > config.load().MAX_FILES_PER_DOC:
                        raise HTTPException(413, "Too many document attachments")
                for file, content in writes:
                    original = snapshot(con, project, file)
                    binary = file.get("binary")
                    if data_size(content, bool(binary)) > (10 * 1024 * 1024 if binary else MAX_TXT):
                        raise HTTPException(413, "Accepted file too large")
                    if file["action"] == "delete" and file["kind"] != "document":
                        payload = base64.b64decode(original or "") if binary else (original or "").encode()
                        trash.archive(con, owner, file["kind"], file["path"], payload, project_id=project, doc_id=file.get("doc_id", ""))
                    name = file["target"] if file["action"] == "rename" or file["kind"] == "document" and file["action"] == "add" else file["path"]
                    if file["action"] in ("add", "rename"):
                        if file["kind"] == "resource":
                            projects.assert_resource_name_free(con, project, name, exempt_name=file["path"] if file["action"] == "rename" else "")
                        elif file["kind"] == "file":
                            projects.assert_file_name_free(con, project, name, exempt_files={(file["doc_id"], file["path"])} if file["action"] == "rename" else set())
                    if file["action"] == "rename" and file["kind"] != "document" and snapshot(con, project, {**file, "path": name}) is not None:
                        raise HTTPException(409, "Rename target exists")
                    if file["kind"] == "document":
                        if file["action"] in ("add", "rename"):
                            if con.execute("SELECT 1 FROM docs WHERE project_id=? AND title=? COLLATE NOCASE AND trashed=0 AND id<>?",
                                           (project, name, file["doc_id"])).fetchone():
                                raise HTTPException(409, "Document title already exists")
                            if file["action"] == "add":
                                if con.execute("SELECT COUNT(*) FROM docs WHERE owner=?", (owner,)).fetchone()[0] >= config.load().MAX_DOCS_PER_USER:
                                    raise HTTPException(400, "Too many docs")
                                now = db.now_iso()
                                con.execute("INSERT INTO docs(id,owner,title,content,project_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                                            (file["doc_id"], owner, file["target"], content, project, now, now))
                                continue
                            if con.execute("SELECT title FROM docs WHERE id=?", (file["doc_id"],)).fetchone()[0] != file["original_title"]:
                                raise HTTPException(409, "Original document title changed")
                            con.execute("UPDATE docs SET title=? WHERE id=?", (name, file["doc_id"]))
                        if file["action"] == "delete":
                            con.execute("UPDATE docs SET content=?,yjs=?,trashed=1,updated_at=? WHERE id=?",
                                        (original or '', sync.room(file['doc_id'])['doc'].get_update(), db.now_iso(), file['doc_id']))
                            deleted_documents.append(file['doc_id'])
                            continue
                        if len((content or "").encode()) > MAX_TXT:
                            raise HTTPException(413, "Document too large")
                        if file["doc_id"] not in doc_before:
                            doc_before[file["doc_id"]] = original or ""
                        room = sync.room(file["doc_id"])
                        trial: Doc = Doc()
                        trial.apply_update(room["doc"].get_update())
                        text = trial.get("typst", type=Text)
                        with trial.transaction():
                            del text[:]
                            text.insert(0, content or "")
                        update = trial.get_update()
                        con.execute(
                            "UPDATE docs SET content=?,yjs=?,updated_at=? WHERE id=?",
                            (content, update, db.now_iso(), file["doc_id"]),
                        )
                        updates.append((room, update, content))
                    elif file["kind"] == "resource":
                        if file["action"] in ("delete", "rename"):
                            con.execute(
                                "DELETE FROM project_resources WHERE project_id=? AND name=?", (project, file["path"])
                            )
                        if content is not None:
                            con.execute(
                                "INSERT INTO project_resources VALUES (?,?,?,?) ON CONFLICT(project_id,name) DO UPDATE SET content=excluded.content,updated_at=excluded.updated_at",
                                (project, name, content, db.now_iso()),
                            )
                    else:
                        paths = [file["path"]] + ([name] if name != file["path"] else [])
                        for path in paths:
                            at = (file["doc_id"], path)
                            if at not in backups:
                                try:
                                    backups[at] = store.get(*at)
                                except FileNotFoundError:
                                    backups[at] = None
                        if file["action"] in ("delete", "rename"):
                            store.delete(file["doc_id"], file["path"])
                            con.execute("DELETE FROM files WHERE doc_id=? AND path=?", (file["doc_id"], file["path"]))
                        if content is not None:
                            data = base64.b64decode(content) if binary else content.encode()
                            store.put(file["doc_id"], name, data)
                            stat = store.doc_path(file["doc_id"], name).stat()
                            con.execute(
                                "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?)",
                                (file["doc_id"], name, stat.st_size, stat.st_mtime, file_type(name)),
                            )
                con.execute(
                    "UPDATE suggestion_packages SET files=?,revision=revision+1,accepted=accepted+?,updated_at=? WHERE id=?",
                    (encode(remaining), accepted, db.now_iso(), package),
                )
                quota.check_quota(owner, 0, con)
                result = get(con, project, package)
        except Exception:
            for at, backup in backups.items():
                if backup is None:
                    store.delete(*at)
                else:
                    store.put(*at, backup)
            raise
        for room, update, content in updates:
            room["doc"].apply_update(update)
            room["text_len"] = len((content or "").encode())
            room["dirty"] = False
            sync._mark_quota_blocked(room, False)
            room["dirty_since"] = 0.0
            room["saved"] = time.monotonic()
    # Snapshot only after commit and lock release: project checkpoints acquire upload locks themselves.
    from backend.services import snapshots as snapsvc

    for doc_id, before in doc_before.items():
        try:
            snapsvc.auto_snap(doc_id, before, label="proposal-accept")
        except (HTTPException, sqlite3.Error, OSError) as e:
            log.warning("proposal accept snap %s: %s", doc_id, e)
    quota.invalidate_quota_cache(owner)
    projects.notify(project)
    return result, updates, deleted_documents
