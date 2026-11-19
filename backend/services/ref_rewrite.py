"""Rewrite static Typst path references when project entries are renamed or moved.

A rename moves project modules (`res_moves`, project-wide) and/or document
files (`file_moves`, per document). Every Typst text in the project is scanned
for quoted paths that resolve, with Typst's own rules, to an existing entry:
`"/x"` from the compile root, anything else relative to the referring file.
A reference is rewritten when its target moved or when the referring file
itself moved (its relative paths would otherwise point elsewhere).

Each document compiles with its own files on top of the project modules
(local paths win). Module texts are shared by every document, so they are
resolved against the modules only; a module that points at a moved document
file is reported as `manual` and left alone.

`plan()` runs before the rename and only reports; `apply()` runs after it and
recomputes everything from the current state, so it never writes stale text.
"""
from __future__ import annotations

import asyncio
import logging
import posixpath
from collections.abc import Callable
from dataclasses import dataclass

from backend import db, sync
from backend.constants import MAX_TXT
from backend.services import projects, quota, resources
from backend.services.docfiles import store

log = logging.getLogger(__name__)

Moves = dict[str, str]
# (start, end, replacement) in str offsets of the text
Edit = tuple[int, int, str]


@dataclass
class Change:
    kind: str  # "main" | "file" | "resource"
    doc_id: str
    doc_title: str
    path: str  # referring file (new location)
    old: str
    new: str
    manual: bool = False

    def label(self) -> str:
        where = f"{self.doc_title}/{self.path}" if self.kind != "resource" else self.path
        return f"{where}: {self.old}"

    def payload(self) -> dict:
        return {"kind": self.kind, "doc_id": self.doc_id, "doc": self.doc_title, "path": self.path,
                "old": self.old, "new": self.new, "manual": self.manual}


def _resolve(ref: str, referrer: str) -> str | None:
    """Typst path semantics: absolute from the root, else relative to the file."""
    if not ref or "\\" in ref or ref.strip() != ref:
        return None
    if ref.startswith("/"):
        p = posixpath.normpath(ref.lstrip("/"))
    else:
        p = posixpath.normpath(posixpath.join(posixpath.dirname(referrer), ref))
    if p in ("", ".") or p == ".." or p.startswith("../"):
        return None
    return p


def _spell(ref: str, target: str, referrer: str) -> str:
    """Write `target` the way `ref` was written (absolute or relative)."""
    if ref.startswith("/"):
        return "/" + target
    start = posixpath.dirname(referrer) or "."
    rel = posixpath.relpath(target, start)
    if ref.startswith("./") and not rel.startswith("../"):
        rel = "./" + rel
    return rel


def rewrite(text: str, old_referrer: str, new_referrer: str,
            lookup: Callable[[str], str | None]) -> list[tuple[Edit, str]]:
    """Edits for one text. `lookup(old_path)` returns the target's new path,
    or None when nothing exists there. Returns ((start, end, new), old_ref)."""
    out: list[tuple[Edit, str]] = []
    for m in resources.REF_RE.finditer(text or ""):
        ref = m.group(1)
        old_target = _resolve(ref, old_referrer)
        if old_target is None:
            continue
        new_target = lookup(old_target)
        if new_target is None:
            continue
        spelled = _spell(ref, new_target, new_referrer)
        if spelled != ref and _resolve(spelled, new_referrer) == new_target:
            out.append(((m.start(1), m.end(1), spelled), ref))
    return out


def apply_edits(text: str, edits: list[Edit]) -> str:
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    return text


def _inverse(moves: Moves) -> Moves:
    return {n: o for o, n in moves.items()}


class _Project:
    """Old and new namespaces of one project around a set of moves."""

    def __init__(self, project_id: str, res_moves: Moves, file_moves: dict[str, Moves], *, after: bool):
        self.res_moves, self.file_moves = res_moves, file_moves
        con = db.connect()
        try:
            self.docs = [(r[0], r[1], r[2]) for r in con.execute(
                "SELECT id,title,content FROM docs WHERE project_id=? AND trashed=0 ORDER BY title,id", (project_id,))]
            rows = {r[0]: r[1] or "" for r in con.execute(
                "SELECT name,content FROM project_resources WHERE project_id=?", (project_id,))}
        finally:
            con.close()
        inv_res = _inverse(res_moves)
        # current names -> old names (the namespace references were written against)
        self.res_old = {(inv_res.get(n, n) if after else n): n for n in rows}
        self.res_texts = rows  # current name -> content
        self.after = after
        self.local: dict[str, dict[str, str]] = {}  # doc -> old path -> current path
        self.local_texts: dict[str, dict[str, str]] = {}
        for d, _title, _content in self.docs:
            if not after:  # the preview reads what it reports; apply re-reads under the upload lock
                self.local_texts[d] = projects.local_texts(d)
            inv = _inverse(file_moves.get(d, {}))
            self.local[d] = {(inv.get(e.path, e.path) if after else e.path): e.path for e in store.list(d)}

    def new_res(self, old: str) -> str:
        return self.res_moves.get(old, old)

    def new_file(self, doc_id: str, old: str) -> str:
        return self.file_moves.get(doc_id, {}).get(old, old)

    def doc_lookup(self, doc_id: str) -> Callable[[str], str | None]:
        local = self.local[doc_id]

        def look(old: str) -> str | None:
            if old in local:  # a document file shadows a module of the same name
                return self.new_file(doc_id, old)
            if old in self.res_old:
                return self.new_res(old)
            return None
        return look

    def res_lookup(self, old: str) -> str | None:
        return self.new_res(old) if old in self.res_old else None

    def moved_local(self, old: str) -> bool:
        return any(old in self.local[d] and self.new_file(d, old) != old for d in self.local)

    def units(self) -> list[tuple[str, str, str, str, str, str]]:
        """(kind, doc_id, title, old path, new path, current key) of every Typst text."""
        out = []
        for d, title, _content in self.docs:
            out.append(("main", d, title, "main.typ", "main.typ", "main.typ"))
            for old, cur in sorted(self.local[d].items()):
                if old.lower().endswith(".typ"):
                    out.append(("file", d, title, old, self.new_file(d, old), cur))
        for old, cur in sorted(self.res_old.items()):
            if old.lower().endswith(".typ"):
                out.append(("resource", "", "", old, self.new_res(old), cur))
        return out

    def text(self, kind: str, doc_id: str, key: str) -> str | None:
        try:
            if kind == "main":
                live = sync.room_text(doc_id)
                return live if live is not None else next(c for d, _t, c in self.docs if d == doc_id) or ""
            if kind == "file":
                cached = self.local_texts.get(doc_id, {}).get(key)
                return cached if cached is not None else store.get(doc_id, key).decode("utf-8")
            return self.res_texts[key]
        except (OSError, UnicodeDecodeError, KeyError, StopIteration):
            return None

    def edits(self, kind: str, doc_id: str, old: str, new: str, text: str) -> tuple[list[tuple[Edit, str]], list[str]]:
        """Edits to apply and references that need a manual fix."""
        if kind != "resource":
            return rewrite(text, old, new, self.doc_lookup(doc_id)), []
        found = rewrite(text, old, new, self.res_lookup)
        manual = []
        for m in resources.REF_RE.finditer(text):
            target = _resolve(m.group(1), old)
            if target and target not in self.res_old and self.moved_local(target):
                manual.append(m.group(1))
        return found, manual


def plan(project_id: str, res_moves: Moves, file_moves: dict[str, Moves]) -> list[Change]:
    """References a rename would touch, computed on the state before it."""
    p = _Project(project_id, res_moves, file_moves, after=False)
    out: list[Change] = []
    for kind, d, title, old, new, key in p.units():
        text = p.text(kind, d, key)
        if text is None:
            continue
        found, manual = p.edits(kind, d, old, new, text)
        out += [Change(kind, d, title, new, ref, e[2]) for e, ref in found]
        out += [Change(kind, d, title, new, ref, ref, manual=True) for ref in manual]
    return out


async def apply(project_id: str, res_moves: Moves, file_moves: dict[str, Moves], actor: str) -> int:
    """Rewrite references after the rename committed. Returns the number of
    rewritten references; a text that changed meanwhile is recomputed."""
    from backend.services.docfiles import save_text_file
    from backend.services.locks import _named_lock
    from backend.services.project_history import auto_document
    from backend.services.sidebar import emit_doc

    if not res_moves and not any(file_moves.values()):
        return 0
    p = await asyncio.to_thread(_Project, project_id, res_moves, file_moves, after=True)
    count = 0
    touched: set[str] = set()
    for kind, d, _title, old, new, key in p.units():
        if kind == "main":
            n = await _patch_main(p, d, old, new)
            if n:
                touched.add(d)
            count += n
            continue

        def write(kind: str = kind, d: str = d, old: str = old, new: str = new, key: str = key) -> int:
            if kind == "file":
                with _named_lock(f"upload:{d}"):
                    text = p.text(kind, d, key)
                    if text is None:
                        return 0
                    found, _ = p.edits(kind, d, old, new, text)
                    result = apply_edits(text, [e for e, _ in found])
                    if not found or len(result.encode("utf-8")) > MAX_TXT:
                        return 0
                    save_text_file(d, key, result, quota.doc_owner(d))
                    return len(found)
            with db.tx() as con:
                row = con.execute("SELECT content FROM project_resources WHERE project_id=? AND name=?",
                                  (project_id, key)).fetchone()
                if not row:
                    return 0
                text = row[0] or ""
                found, _ = p.edits(kind, d, old, new, text)
                result = apply_edits(text, [e for e, _ in found])
                if not found or len(result.encode("utf-8")) > MAX_TXT:
                    return 0
                con.execute("UPDATE project_resources SET content=?,updated_at=? WHERE project_id=? AND name=?",
                            (result, db.now_iso(), project_id, key))
                return len(found)
        try:
            n = await asyncio.to_thread(write)
        except Exception as e:  # one unwritable text must not undo the rename
            log.warning("ref_rewrite %s %s/%s failed: %s", project_id, d, key, e)
            n = 0
        if n and kind == "file":
            touched.add(d)
        count += n
    for d in touched:
        try:
            auto_document(d, actor=actor)  # warn-only, like the text-file save route
            emit_doc(d, "file")
        except Exception as e:
            log.warning("ref_rewrite notify %s failed: %s", d, e)
    return count


async def _patch_main(p: _Project, doc_id: str, old: str, new: str) -> int:
    def compute(text: str) -> list[Edit]:
        found, _ = p.edits("main", doc_id, old, new, text)
        result = apply_edits(text, [e for e, _ in found])
        return [e for e, _ in found] if len(result.encode("utf-8")) <= MAX_TXT else []

    n = await sync.patch_text(doc_id, compute)
    if n is not None:
        return n
    # No live room: the stored text is the source of truth.
    def stored() -> int:
        from backend.services.snapshots import auto_snap
        with db.tx() as con:
            row = con.execute("SELECT content,trashed FROM docs WHERE id=?", (doc_id,)).fetchone()
            if not row or row["trashed"]:
                return 0
            text = row["content"] or ""
            edits = compute(text)
            if not edits:
                return 0
            con.execute("UPDATE docs SET content=?,yjs=NULL,updated_at=? WHERE id=?",
                        (apply_edits(text, edits), db.now_iso(), doc_id))
        try:
            auto_snap(doc_id, text, label="rename")
        except Exception as e:
            log.warning("ref_rewrite snap %s: %s", doc_id, e)
        return len(edits)
    try:
        return await asyncio.to_thread(stored)
    except Exception as e:
        log.warning("ref_rewrite main %s failed: %s", doc_id, e)
        return 0
