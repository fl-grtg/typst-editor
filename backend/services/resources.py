"""Account-global text resources: .typ templates, .bib libraries, .csv tables.

One `templates` table holds all three kinds (extension decides the kind, no
migration: old .typ rows are untouched). Resources are per-account, never
public. Shared docs compile against the OWNER's reachable resources
(transitive closure over quoted names, doc-local files win); viewers never
see the owner's unrelated library.
"""
from __future__ import annotations

import posixpath
import re
import sqlite3
from pathlib import Path

from fastapi import HTTPException

from backend import db

RESOURCE_EXTS = {".typ": "template", ".bib": "library", ".csv": "table", ".tsv": "table", **dict.fromkeys((".json", ".yaml", ".yml", ".toml", ".xml", ".txt", ".csl"), "data")}
REF_RE = re.compile(r'"([^"\n]{1,240})"')
# Explicit bounds (not silent truncation): per-text scan cap + total closure
# cap. Typical docs reach a handful of files; the caps only stop cycles and
# pathological inputs. A capped-away file surfaces as a normal Typst
# "file not found" compile error, never as silent success.
REF_MAX_PER_TEXT = 200
REACHABLE_MAX = 500
# Backwards-compat alias (old importers): total-closure cap.
REF_MAX = REACHABLE_MAX
# `main.typ` is the doc itself: a resource by that name would shadow it in
# every compile (`/main.typ` twice). New/updated resources reject it;
# get/read/delete keep working for any pre-existing rows.
RESERVED_NAMES = frozenset({"main.typ"})


def kind_of(name: str) -> str:
    return RESOURCE_EXTS.get(Path(name or "").suffix.lower(), "")


def res_name(raw: str) -> str:
    n = re.sub(r"[^A-Za-z0-9._ ()-]", "_", Path(raw or "").name.strip().lstrip("."))[:100]
    if not n or kind_of(n) == "":
        raise HTTPException(400, "Unsupported text resource extension")
    return n


def is_reserved(name: str) -> bool:
    return (name or "").strip().lower() == "main.typ"


def insert_line(name: str) -> str:
    low = (name or "").lower()
    if low.endswith(".bib"):
        return f'#bibliography("{name}")'
    if low.endswith(".typ"):
        return f'#include "{name}"'
    if low.endswith(".csv"):
        return f'#csv("{name}")'
    suffix = Path(low).suffix
    loader = {".tsv": "csv", ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".xml": "xml", ".txt": "read", ".csl": "read"}.get(suffix)
    if loader:
        delimiter = ', delimiter: "\\t"' if suffix == ".tsv" else ""
        return f'#let data = {loader}("{name}"{delimiter})'
    return ""


def _is_plausible_ref(raw: str) -> bool:
    """Quoted paths may contain spaces, including generated copy names."""
    n = (raw or "").strip()
    if not n or len(n) > 240:
        return False
    if kind_of(n) == "" and kind_of(Path(n).name) == "":
        return False
    return True


def refs_in_text(text: str) -> list[str]:
    out, seen = [], set()
    for m in REF_RE.finditer(text or ""):
        n = m.group(1).strip()
        if not n or n in seen or not _is_plausible_ref(n):
            continue
        seen.add(n)
        out.append(n)
        if len(out) >= REF_MAX_PER_TEXT:
            break
    return out


def _norm_ref(ref: str) -> str:
    return (ref or "").strip().replace("\\", "/")


def _clamp_root(p: str) -> str:
    # posixpath.normpath("a/../../b") -> "../b": clamp escapes to root
    # (compile roots at the doc dir; nothing lives above it).
    while p == ".." or p.startswith("../"):
        p = p[3:] if p.startswith("../") else ""
    p = p.lstrip("/")
    if p in ("", "."):
        return ""
    return p


def _resolve_ref(referrer: str | None, ref: str,
                 local: dict[str, str], shelf: dict[str, str]) -> str | None:
    """Resolve one quoted ref to a key in `local` (doc wins) or `shelf`.

    `referrer` is the importing file's path (`"main.typ"` for main text,
    else the local/resource path). Typst resolves relative to the
    importing file, so `sub/part.typ` importing `"leaf.typ"` means
    `sub/leaf.typ` first, then the doc root, then the owner shelf.
    Returns the resolved key (local path or shelf name) or None.
    """
    raw = _norm_ref(ref)
    if not raw or not _is_plausible_ref(raw):
        return None
    cands: list[str] = []
    if referrer:
        parent = posixpath.dirname(referrer) if "/" in referrer else ""
        joined = posixpath.normpath(posixpath.join(parent, raw)) if parent else posixpath.normpath(raw)
        cands.append(_clamp_root(joined))
    cands.append(_clamp_root(posixpath.normpath(raw)))
    for c in cands:
        if c and c in local:
            return c
    for c in cands:
        if c and c in shelf:
            return c
    if any(ch.isspace() for ch in raw):
        return None
    base = posixpath.basename(raw)
    if base in local:
        return base
    if base in shelf:
        return base
    return None


def list_resources(con: sqlite3.Connection, owner: str) -> list[dict]:
    rows = con.execute("SELECT name, content, line, folder, updated_at FROM templates "
                       "WHERE owner=? ORDER BY name", (owner,)).fetchall()
    return [{"name": r["name"], "content": r["content"] or "", "line": r["line"] or "",
             "folder": r["folder"] or "", "kind": kind_of(r["name"]),
             "updated_at": r["updated_at"] or ""} for r in rows]


def _is_code_path(path: str | None) -> bool:
    # Only Typst sources import further files. .bib/.csv are leaves:
    # scanning their data contents for `"*.typ"` would pull phantom deps.
    if not path:
        return True  # main text is always code
    return Path(path).suffix.lower() == ".typ"


def reachable_closure(shelf: dict[str, str], local: dict[str, str],
                      main_text: str) -> dict[str, str]:
    """Path-aware transitive closure over main + local .typ files + shelf.

    Keys are original paths (local, possibly nested) or shelf names
    (flat). Cycle-safe via `visited`; bounded by REACHABLE_MAX.
    """
    got: dict[str, str] = {}
    visited: set[str] = set()
    queue: list[tuple[str | None, str]] = [("main.typ", main_text or "")]
    for path, content in local.items():
        if _is_code_path(path):
            queue.append((path, content or ""))
    while queue and len(visited) < REACHABLE_MAX:
        referrer, text = queue.pop(0)
        for ref in refs_in_text(text):
            key = _resolve_ref(referrer, ref, local, shelf)
            if not key or key in visited:
                continue
            if key in local:
                visited.add(key)
                got[key] = local[key]
                if _is_code_path(key) and len(visited) < REACHABLE_MAX:
                    queue.append((key, local[key] or ""))
            elif key in shelf:
                visited.add(key)
                got[key] = shelf[key]
                if _is_code_path(key) and len(visited) < REACHABLE_MAX:
                    queue.append((key, shelf[key] or ""))
    return got


def reachable(owner_texts: dict[str, str], entry_texts: list[str]) -> dict[str, str]:
    """Flat transitive closure (backwards-compat wrapper).

    Path-agnostic: exact-name matches only. Only `.typ` contents are
    expanded (`.bib`/`.csv` are leaves). Cycle-safe, bounded.
    """
    got: dict[str, str] = {}
    queue = [n for t in entry_texts for n in refs_in_text(t)]
    while queue and len(got) < REACHABLE_MAX:
        n = queue.pop(0)
        if n in got or n not in owner_texts:
            continue
        got[n] = owner_texts[n]
        if _is_code_path(n):
            queue.extend(x for x in refs_in_text(got[n]) if x not in got)
    return got


def doc_effective(owner: str, main_text: str, local_files: dict[str, str], doc_id: str = "") -> dict:
    """Compile set for one doc: owner's reachable resources, local files win.

    Returns `resources` (name -> content, reachable shelf names NOT shadowed
    by an exact local path), `local` (sorted local paths), and `versions`
    (name -> updated_at for the reachable set, so owner tabs can show
    staleness without fetching the whole shelf).
    """
    con = db.connect()
    try:
        d = con.execute("SELECT project_id FROM docs WHERE id=?", (doc_id,)).fetchone() if doc_id else None
        project_id = d["project_id"] if d else None
        if project_id:
            rows = con.execute("SELECT name,content,updated_at FROM project_resources WHERE project_id=?", (project_id,)).fetchall()
        else:
            rows = con.execute("SELECT name, content, updated_at FROM templates WHERE owner=?", (owner,)).fetchall()
    finally:
        con.close()
    shelf = {r["name"]: r["content"] or "" for r in rows}
    versions = {r["name"]: r["updated_at"] or "" for r in rows}
    found = reachable_closure(shelf, local_files or {}, main_text or "")
    resources = {n: c for n, c in found.items() if n not in (local_files or {})}
    return {"owner": owner, "project_id": project_id,
            "resources": resources,
            "local": sorted(local_files or {}),
            "versions": {n: versions.get(n, "") for n in resources}}


def copy_name(name: str, number: int = 1) -> str:
    suffix = Path(name).suffix
    stem = name[:-len(suffix)] if suffix else name
    tag = ' (copy)' if number == 1 else f' (copy {number})'
    return stem[:100 - len(tag) - len(suffix)] + tag + suffix
