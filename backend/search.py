"""Shared FTS5 + filename/.bib search for /api/search and MCP op_search.

docs_fts(title, content) is keyed by docs.rowid (docs.id is TEXT, so FTS
content-sync is not an option); triggers in schema.sql / db._migrate_v12
keep it in sync. Filenames and .bib keys live on the filesystem, so no
trigger can index them: they are matched per search via a LIKE-style
substring scan over the doc's files dir (hybrid, capped at 20 hits).

Matching:
  FTS5 prefix over unicode61 tokens for persisted title/content, plus a
  substring fallback over live room text / title / filenames / .bib keys
  so dirty live rooms and mid-word queries keep working.

Snippet:
  snippet(docs_fts, ...) for FTS hits; a "...window..." around the live
  text when only the live room matches (live is preferred for display).
"""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from pathlib import Path

MAX_HITS = 20
MAX_Q = 50
MIN_Q = 2
SNIPPET_TOKENS = 15
BIB_MAX_BYTES = 1_000_000

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_BIB_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s\}]+)")


def normalize_query(raw: str) -> str:
    return (raw or "").strip()[:MAX_Q]


def fts_query(q: str) -> str | None:
    """Build a safe FTS5 MATCH string: quoted prefix terms ANDed.

    Tokens come from [^\\W_] so they hold no FTS operators/quotes;
    quoting still guards reserved words (AND/OR/NOT). None when the
    query has no indexable token (e.g. "__", "%%").
    """
    toks = _TOKEN_RE.findall(q)
    if not toks:
        return None
    return " AND ".join(f'"{t}"*' for t in toks)


def live_snippet(txt: str, q: str) -> tuple[str, int]:
    i = txt.lower().find(q.lower())
    if i < 0:
        return "", -1
    return ("..." + txt[max(0, i - 40):i + 80].replace("\n", " ") + "...", i)


def extract_bib_keys(text: str) -> list[str]:
    return _BIB_KEY_RE.findall(text)


def scan_files(doc_id: str, files_dir: Path, q_lower: str) -> tuple[list[str], list[str]]:
    """Filenames + .bib keys containing q (case-insensitive substring)."""
    d = files_dir / doc_id
    try:
        if not d.is_dir():
            return ([], [])
        entries = list(d.iterdir())
    except OSError:
        return ([], [])
    names: list[str] = []
    keys: list[str] = []
    for p in entries:
        try:
            if not p.is_file() or ".tmp." in p.name:
                continue
        except OSError:
            continue
        if q_lower in p.name.lower():
            names.append(p.name)
        if p.suffix.lower() == ".bib":
            try:
                if p.stat().st_size > BIB_MAX_BYTES:
                    continue
                txt = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for k in extract_bib_keys(txt):
                if q_lower in k.lower():
                    keys.append(k)
    return (names, keys)


def file_snippet(names: list[str], keys: list[str]) -> str:
    bits: list[str] = []
    if names:
        bits.append("file: " + names[0])
    if keys:
        bits.append("bib: " + keys[0])
    if not bits:
        return ""
    return "..." + " | ".join(bits) + "..."


def _fts_hits(con: sqlite3.Connection, user: str, fq: str) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT d.id, d.title, d.owner, d.content, d.updated_at, "
        f"snippet(docs_fts, 1, '', '', '...', {SNIPPET_TOKENS}) AS fts_snip "
        "FROM docs_fts JOIN docs d ON d.rowid=docs_fts.rowid "
        "LEFT JOIN shares s ON s.doc_id=d.id AND s.username=? "
        "WHERE d.trashed=0 AND (d.owner=? OR s.username=?) AND docs_fts MATCH ? "
        "ORDER BY d.updated_at DESC LIMIT 20",
        (user, user, user, fq)).fetchall()


def _like_rows(con: sqlite3.Connection, user: str, q: str) -> list[sqlite3.Row]:
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return con.execute(
        "SELECT d.id, d.title, d.owner, d.content, d.updated_at FROM docs d "
        "LEFT JOIN shares s ON s.doc_id=d.id AND s.username=? "
        "WHERE d.trashed=0 AND (d.owner=? OR s.username=?) "
        "AND (d.title LIKE ? ESCAPE '\\' OR d.content LIKE ? ESCAPE '\\') "
        "ORDER BY d.updated_at DESC LIMIT 20", (user, user, user, like, like)).fetchall()


def _use_fts(q: str) -> bool:
    """FTS only for plain word queries; % _ etc. keep LIKE substring semantics."""
    compact = q.replace(" ", "")
    return bool(compact) and _TOKEN_RE.fullmatch(compact) is not None


def search_visible(user: str, raw_q: str, con: sqlite3.Connection,
                   files_dir: Path, room_text: Callable[[str], str | None]) -> list[dict]:
    """Ordered hit dicts (max 20): id/title/owner/snippet/pos/updated_at.

    Falls back to LIKE when docs_fts is missing or the MATCH errors
    (half-migrated DB), so search never 500s.
    """
    q = normalize_query(raw_q)
    if len(q) < MIN_Q:
        return []
    q_lower = q.lower()
    hits: list[dict] = []
    seen: set[str] = set()
    if _use_fts(q):
        fq = fts_query(q)
        fts_rows: list[sqlite3.Row] = []
        if fq is not None:
            try:
                fts_rows = _fts_hits(con, user, fq)
            except sqlite3.OperationalError:
                fts_rows = []
        for r in fts_rows:
            live = room_text(r["id"])
            base = r["content"] or ""
            txt = live if live is not None else base
            pos = txt.lower().find(q_lower)
            if live is not None and pos >= 0:
                snippet = live_snippet(live, q)[0]
            else:
                snippet = r["fts_snip"] or ""
                if pos < 0:
                    pos = base.lower().find(q_lower)
            hits.append({"id": r["id"], "title": r["title"], "owner": r["owner"],
                         "snippet": snippet, "pos": pos, "updated_at": r["updated_at"]})
            seen.add(r["id"])
            if len(hits) >= MAX_HITS:
                return hits
    else:
        # Special chars (%, _, ...) or missing FTS: literal LIKE substring,
        # same escaping as before (test_search_escapes_wildcards).
        try:
            like_rows = _like_rows(con, user, q)
        except sqlite3.OperationalError:
            like_rows = []
        for r in like_rows:
            live = room_text(r["id"])
            txt = live if live is not None else (r["content"] or "")
            snippet, pos = live_snippet(txt, q)
            hits.append({"id": r["id"], "title": r["title"], "owner": r["owner"],
                         "snippet": snippet, "pos": pos, "updated_at": r["updated_at"]})
            seen.add(r["id"])
            if len(hits) >= MAX_HITS:
                return hits
    # Supplement: live-only edits, title hits FTS tokenization missed,
    # plus filename / .bib-key matches over the files dir.
    try:
        cands = con.execute(
            "SELECT d.id, d.title, d.owner, d.content, d.updated_at FROM docs d "
            "LEFT JOIN shares s ON s.doc_id=d.id AND s.username=? "
            "WHERE d.trashed=0 AND (d.owner=? OR s.username=?) "
            "ORDER BY d.updated_at DESC", (user, user, user)).fetchall()
    except sqlite3.OperationalError:
        return hits[:MAX_HITS]
    for r in cands:
        if len(hits) >= MAX_HITS:
            break
        if r["id"] in seen:
            continue
        live = room_text(r["id"])
        txt = live if live is not None else (r["content"] or "")
        if q_lower in txt.lower():
            snippet, pos = live_snippet(txt, q)
            hits.append({"id": r["id"], "title": r["title"], "owner": r["owner"],
                         "snippet": snippet, "pos": pos, "updated_at": r["updated_at"]})
            seen.add(r["id"])
        elif q_lower in (r["title"] or "").lower():
            pos = txt.lower().find(q_lower)
            hits.append({"id": r["id"], "title": r["title"], "owner": r["owner"],
                         "snippet": "", "pos": pos, "updated_at": r["updated_at"]})
            seen.add(r["id"])
        else:
            names, keys = scan_files(r["id"], files_dir, q_lower)
            if names or keys:
                pos = txt.lower().find(q_lower)
                hits.append({"id": r["id"], "title": r["title"], "owner": r["owner"],
                             "snippet": file_snippet(names, keys), "pos": pos,
                             "updated_at": r["updated_at"]})
                seen.add(r["id"])
    return hits[:MAX_HITS]
