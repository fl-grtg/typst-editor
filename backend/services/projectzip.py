"""Source ZIP import: validate first, then publish one document with local files."""
from __future__ import annotations

import io
import shutil
import sqlite3
import stat
import zipfile
from pathlib import PurePosixPath

from fastapi import HTTPException

from backend import config, db, deps
from backend.constants import EXPORT_MAX, MAX_TXT, TITLE_MAX, UPLOAD_MAX
from backend.services import projects, quota
from backend.services.docfiles import file_type, safe_name, store
from backend.services.sidebar import notify_sidebar


def read_project_zip(data: bytes) -> tuple[str, list[tuple[str, bytes]]]:
    if len(data) > UPLOAD_MAX:
        raise HTTPException(413, "ZIP too large (max 10 MB)")
    limits = config.load()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = [e for e in archive.infolist() if not e.is_dir()]
            if len(entries) > limits.MAX_FILES_PER_DOC + 1:
                raise HTTPException(400, "Too many files in ZIP")
            if sum(e.file_size for e in entries) > EXPORT_MAX:
                raise HTTPException(413, "Uncompressed ZIP too large (max 100 MB)")
            mains = [e for e in entries if PurePosixPath(e.filename).name == "main.typ"]
            if len(mains) != 1:
                raise HTTPException(400, "ZIP must contain exactly one main.typ")
            prefix = mains[0].filename.removesuffix("main.typ")
            files, seen = [], set()
            actual_total = 0
            main = ""
            for entry in entries:
                raw = entry.filename
                if raw.startswith("/") or "\\" in raw or ".." in PurePosixPath(raw).parts or stat.S_ISLNK(entry.external_attr >> 16):
                    raise HTTPException(400, "Unsafe ZIP path")
                if prefix and not raw.startswith(prefix):
                    raise HTTPException(400, "All ZIP files must be in the main.typ folder")
                name = raw[len(prefix):]
                if not name or safe_name(name) != name or name.casefold() in seen:
                    raise HTTPException(400, "Invalid or duplicate ZIP path")
                seen.add(name.casefold())
                limit = MAX_TXT if PurePosixPath(name).suffix.lower() in deps.TEXT_SUFFIX else UPLOAD_MAX
                if entry.file_size > limit:
                    raise HTTPException(413, "File in ZIP too large")
                with archive.open(entry) as stream:
                    content = stream.read(limit + 1)
                actual_total += len(content)
                if len(content) > limit or actual_total > EXPORT_MAX:
                    raise HTTPException(413, "Uncompressed ZIP data too large")
                if PurePosixPath(name).suffix.lower() in deps.TEXT_SUFFIX:
                    try:
                        text = content.decode("utf-8-sig")
                    except UnicodeDecodeError as e:
                        raise HTTPException(400, "Text files in ZIP must be UTF-8") from e
                    content = text.encode("utf-8")
                if name == "main.typ":
                    main = content.decode("utf-8")
                else:
                    files.append((name, content))
            return main, files
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError) as e:
        raise HTTPException(400, "Invalid or unsupported ZIP") from e


def import_project_zip(user: str, title: str, folder: str, data: bytes, project_id: str | None = None) -> dict:
    title = title.strip()
    if not title or len(title) > TITLE_MAX:
        raise HTTPException(400, f"Title: 1-{TITLE_MAX} chars")
    folder = deps.check_folder_name(folder) if folder.strip() else ""
    main, files = read_project_zip(data)
    did, now = db.new_id("d_"), db.now_iso()
    root = deps.get_files_dir().resolve()
    target = (root / did).resolve()
    target.relative_to(root)

    owner = user
    if project_id:
        with db.tx() as con:
            projects.require(con, project_id, user, edit=True)
            owner = con.execute('SELECT owner FROM projects WHERE id=?', (project_id,)).fetchone()[0]

    created_project_id = None

    def rollback() -> None:
        with db.tx() as con:
            con.execute("DELETE FROM docs WHERE id=? AND owner=?", (did, owner))
            if created_project_id:
                con.execute("DELETE FROM projects WHERE id=? AND NOT EXISTS (SELECT 1 FROM docs WHERE project_id=?)", (created_project_id, created_project_id))
        if target.exists():
            shutil.rmtree(target)

    try:
        with quota.quota_guard(owner, len(main.encode("utf-8")) + sum(len(b) for _, b in files), rollback=rollback):
            for name, content in files:
                store.put(did, name, content)
            with db.tx() as con:
                if con.execute("SELECT COUNT(*) AS n FROM docs WHERE owner=?", (owner,)).fetchone()["n"] >= config.load().MAX_DOCS_PER_USER:
                    raise HTTPException(400, "Too many docs")
                con.execute("INSERT INTO docs (id, owner, title, content, folder, created_at, updated_at) VALUES (?,?,?,?,?,?,?)", (did, owner, title, main, folder, now, now))
                for name, content in files:
                    info = store.stat(did, name)
                    if info is None:
                        raise OSError("Imported file disappeared")
                    con.execute("INSERT INTO files (doc_id, path, size, mtime, type) VALUES (?,?,?,?,?)", (did, name, len(content), info.mtime, file_type(name)))
                prior = con.execute("SELECT project_id FROM legacy_project_folders WHERE owner=? AND folder=?", (user, folder.split("/")[0])).fetchone() if folder else None
                if project_id:
                    projects.require(con, project_id, user, edit=True)
                pid = projects.attach_doc(con, did, project_id)
                if pid:
                    # #7: importing into an existing project must not add an
                    # attachment name another sibling doc already shows.
                    for name, _content in files:
                        projects.assert_file_name_free(con, pid, name, exempt_files={(did, name)})
                if not prior and not project_id:
                    created_project_id = pid
    except sqlite3.IntegrityError as e:
        rollback()
        raise HTTPException(400, "Title already exists") from e
    except sqlite3.OperationalError as e:
        rollback()
        raise deps.busy_503("import_project_zip", e) from e
    except Exception:
        rollback()
        raise
    quota.invalidate_quota_cache(owner)
    if project_id:
        projects.notify(project_id)
    else:
        notify_sidebar(user)
    return {"id": did, "files": len(files)}
