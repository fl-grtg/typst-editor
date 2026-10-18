---
name: typst-editor
description: Self-hosted Typst docs via MCP (ls, read, create, edit, view, export, search, upload, comment, suggest, suggestions). Use for /docs, /shared, /templates, /projects work through the typst-editor server.
---

# Typst Editor — MCP Agent Skill

Work on the user's self-hosted Typst docs through MCP (Streamable HTTP).

## 0. Human setup (once — walk the user through this if anything is missing)

1. Server URL: local `http://127.0.0.1:8978` or remote `https://host`. From this checkout: `docker compose -f compose.yml -f compose.prerelease.yml up -d --build` runs the current candidate (tag `0.2.0rc1`, built locally); plain `docker compose up -d` pulls the older published stable (`v0.1.0` — no MCP server at all). Port via `PORT`. The user needs an account on it — server default is `invite-only`, so an invite code (or the admin) may be required first; `closed` needs the admin (set `REGISTRATION`, no UI for it), no self-registration. Fresh Docker installs print the token once on first start (`docker compose logs app | grep "invite code"`; also stored `chmod 600` as `DATA_DIR/.invite_token`).
2. In the web UI (login → Settings → API keys → Create), with a **name** (required):
   - **Role: Reviewer** for read/comment jobs; **Editor** only if files must change. (Default: Editor.)
   - **Expires:** 30–90 days recommended. (Default: never.)
   - The secret (`tpe_<prefix>_<secret>`) is shown **once** — copy it now. Only its hash is stored.
3. Register the server (insert URL + key):

   Claude Code:
   ```
   claude mcp add --transport http typst-editor <server>/mcp \
     --header "Authorization: Bearer tpe_..."
   ```

   OpenCode (`opencode.json`):
   ```json
   { "mcp": { "typst-editor": {
     "type": "remote", "url": "<server>/mcp",
     "headers": { "Authorization": "Bearer tpe_..." } } } }
   ```
4. Hand this file + the key to the agent. Everything below is the agent's job.

## 1. Connect

- Endpoint `<server>/mcp`, header `Authorization: Bearer <key>` only (no cookie).
- Tool errors arrive as `isError: true` at HTTP 200 — read the message, never trust the 200.

## 2. Work loop

```
ls -> read -> edit -> view -> see (§8) -> fix (= re-edit + re-view) -> export -> save (§9)
```

Copy paths from `ls` output, never invent them.

## 3. Tools

| Tool | Does |
| --- | --- |
| `ls(path="/")` | `/`, `/docs`, `/shared`, `/templates`, `/projects` (also a project `/{id}` + its `docs`/`resources`), or a doc path (its files) |
| `read(path, offset=1, limit=0)` | line window over doc / text file / template / project resource (offset 1-based, limit 0 = all, past-the-end → `""`) → `content` + echoed `offset` + `total_lines` + `last_seen` (pass to `edit`); doc reads add `live` (text came from the in-memory live room, e.g. an open editor) |
| `create(path, content="")` | new doc, file, template, or project doc/resource (template suffix must be a known text type: `.typ`, `.bib`, `.csv`, `.tsv`, `.json`, `.yaml`/`.yml`, `.toml`, `.xml`, `.txt`, `.csl` — else `404`). `400` if it exists, project collisions → `409`; binary names need `upload` instead |
| `edit(path, old_string, new_string, replace_all=false, last_seen=null)` | anchor edit (§5), max 200000 UTF-8 bytes |
| `search(query)` | doc main text + reachable project resources (titles + content), min 2 chars, max 20 hits |
| `upload(path, content_base64, filename=null)` | attachment (`…/{File}` or doc + `filename`), max 10 MB |
| `comment(path, anchor, text, quote="", parent_id=null)` | `anchor` = 1-based line number (`1` = first line, max 10M; `0` is accepted as an alias for `1`); text ≤2000 chars; **docs only** (file/template paths → `400`); one reply level; create-only, rest in UI |
| `suggest(path, old_string, new_string, text="")` | Propose a **document** edit without changing source. Any readable role/key may propose. Original must match exactly once (include context); use `old_string=""` only for an empty document. Replacement may be empty to delete. Original/replacement each max 20,000 chars, explanation max 2,000. Returns pending id/anchor. `409` means missing/ambiguous original: re-read before proposing again; `400` if nothing changes; `413` beyond 200 pending proposals or 512 KB pending payload per document. |
| `suggestions(path)` | List a document's proposals: 200 latest + `total`, each with `id`, `author`, `anchor`, `quote` (original, ≤500 chars), explanation `text`, `status`, `created_at`. Full original/replacement text is not returned. Only an editor or owner can accept/reject in the UI; there is no MCP acceptance tool. File, template and resource paths are unsupported for proposals (`400`). |
| `view(path, pages="1-5", scale=1.0)` | doc pages as viewable image blocks (longest side ≤1280px) → image blocks + `count` + `total_pages` + `cache_hit` + `last_seen`; pages format `"2"`, `"1-5"`, `"6-10"`, `"1-3,5"` — numbers 1-20, max 20 per call; `scale` 0.5-3.0 (default 1.0 → 144 ppi). Compile errors → `422` with `diagnostics: [{file, line, col, message}]`. No manual decode needed — see §8 |
| `export(path, format="pdf", pdf_standard="none", pages="", ppi=0)` | doc as file → `format` + `mime` + `filename` + `content_base64` + `size_bytes`. Formats: `pdf` (full multi-page PDF), `svg`/`png` (single page directly, multi-page docs arrive as ZIP of `page-{n}` files), `zip` (document source bundle: `main.typ` + sources at their original relative paths + `SKIPPED.txt` if oversized — not a project ZIP, no project round-trip). Options (§9): `pdf_standard`, `pages`, `ppi`. Read-only: reviewer keys work. Always decode + save, see §9 |

## 4. Paths

- `/docs/{Title}` = own doc (readable AND its file list; `ls` a file or template path → `400`, use `read`), `/docs/{Title}/{File}` = text/attachment (legacy alias; new docs live in a project)
- `/projects/{id}` = project; `/projects/{id}/docs` = its docs; `/projects/{id}/docs/{Title}[/{File}]` = unambiguous doc path (doc titles per project unique case-insensitive; project titles per owner unique case-insensitive via v19 NOCASE index: create auto-suffixes ` (2)`…, rename → `409`); `/projects/{id}/resources[/{Name}]` = shared project library
- `/shared/{Owner}/{Title}[/{File}]` = doc shared with the key owner (legacy single-doc guests: only that doc + its reachable sources, no member list)
- `/templates/{Name}` = private collection entry (suffix `.typ`, `.bib`, `.csv`, `.tsv`, `.json`, `.yaml`/`.yml`, `.toml`, `.xml`, `.txt` or `.csl`; no compile fallback; use explicit pull/copy to bring it into a project as an independent, separately counted copy)
- `/` inside a title breaks the path → such titles are unreachable (`400` at create)

## 5. Edit rules

- `old_string` required, 2–3 lines of context, copied from `read` — never guessed.
- `0` matches → `409 anchor-gone`: re-`read`, then retry with a bigger anchor.
- `>1` matches → `409 anchor-ambiguous`: add context, or `replace_all=true` (renames).
- `last_seen` is optional: stale marker + clean anchor still applies (returns `stale: true`).
- Binary `read` → `400`: `view` the parent doc (renders only embedded content), `upload` to replace the file.

## 6. On errors

- `404` → path is wrong or renamed: `ls` the parent again, never retry blindly.
- `403` → missing right: ask the human for a share (or a stronger key). Reviewer keys/shares are read + comment + propose only — that is the minimum of key role and share role. Project guests see only their shared docs. Rename/share/delete/invite/resolve don't exist as MCP tools — human in the UI (file/resource rename there is two-step: `rename-entry-preview` returns `{name, version, references}`, `rename-entry` requires that `version`; UI shows static references + dynamic-path hint and asks for confirmation, no auto-rewrite; removing a project member shows an explicit broad-revoke warning before confirming).
- `409` → ambiguous legacy title (same title in several projects): switch to `/projects/{id}/docs/{Title}`; project/doc title collisions on create/rename also → `409` (project create auto-suffixes instead); stale file/resource rename `version` → `409` (re-run preview in UI); for `edit` it can also mean anchor-gone/anchor-ambiguous (see §5).
- `410` → doc is trashed (restore in UI) or retired folder route (use `/projects`); stop and tell the human.
- `429` → rate limit (60/min): back off, don't retry-loop. REST export serializes per user across docs (`429 Export already running`) — wait, then retry once.
- `503` → compile slots busy (`Compile busy, try again`, Retry-After 5 s; 2 slots + 4 queue, shared by all view/export calls) or a busy DB: wait briefly, retry once, don't loop.
- `export` errors: bad `format` or file/template path → `400`; unknown doc → `404`; compile errors → `422` with `diagnostics` (same shape as `view`: fix the quoted line, re-export); source/output over 100 MB → `413`; missing `typst` CLI or 30s timeout → `500`.

## 7. Limits

- `search` <2 chars: no hits. `upload`: 200 files/doc, 500 MB/user default cap + one-time permanent `migration_bytes` allowance for the existing project library (effective limit `quota.user_cap`, visible via `GET /api/me` `storage{used,limit,migration_allowance}` + Settings; new copies count normally; over quota → `413`). Text: max 200000 UTF-8 bytes (`create`/`edit` fail above). `view`: needs the `typst` CLI on the server (Docker image has it).
- Server version `0.2.0rc1` (`pyproject.toml`) is a prerelease candidate, not yet published; see `RELEASE_NOTES.md` (candidate draft, no full acceptance claimed). Live-doc write-behind persists on a nominal ~2 s interval + last disconnect with no guaranteed loss bound (failed flushes, quota blocks or load can delay it).
- `export`: needs the `typst` CLI too (except `zip`, which is pure bundling). Source + output capped at 100 MB (`413` beyond); compile timeout 30s (`500`). Exports the live text if someone has the doc open, else the saved content. Filename is sanitized from the title (`<stem>.<fmt>`, multi-page svg/png as `<stem>-<fmt>.zip`).

## 8. Seeing pages (pixel check)

- `view` returns directly viewable image blocks plus structured `count` + `total_pages` + `cache_hit` + `last_seen` (+ echoed `pages`, `scale`). Look at the images, never decode or save anything manually.
- Pages format: comma-separated `"N"` or `"A-B"` parts (e.g. `"2"`, `"1-5"`, `"6-10"`, `"1-3,5"`). Page numbers 1-20, at most 20 pages per call — longer docs need several calls (`1-5`, `6-10`, …). Default `pages="1-5"` renders the first five. `count` = images in this call, `total_pages` = pages in the whole doc.
- `scale` 0.5-3.0 (default 1.0 = 144 ppi): higher = sharper at the same 1280px cap. Cache holds 20 entries / 20 MB (key includes pages + scale).
- `total_pages` = whole-doc page count via PDF compile (cached per content, 20 entries); if the count fails, it falls back to the highest requested page.
- Compile errors come back as `422` with structured `diagnostics` (`[{file, line, col, message}]`): fix the quoted line, then re-`view`. `typst` CLI missing → `500`.
- `cache_hit: true` means identical input to a previous render: reuse what you already saw.

## 9. Saving exports (pdf/svg/png/zip)

- `export` returns text-only: base64-decode `content_base64` and write it to `filename` — never paste the base64 anywhere, never re-encode.
- Verify after writing: check `size_bytes` matches the file size, and the magic bytes (`%PDF-` for pdf, `<svg` for svg, PNG signature for png, `PK` for zip).
- `mime` tells you the real kind: multi-page `svg`/`png` come back as `application/zip` (filename `<stem>-svg.zip` / `<stem>-png.zip`) containing one `page-{n}.svg/.png` per page — unzip first, then use the pages.
- `zip` format is sources, not renderings: `main.typ` + sources at their original paths (e.g. `notes.txt`, `sub/pic.png`) (+ `SKIPPED.txt` listing oversized attachments left out). Use it to hand the human the editable bundle.
- Options: `pdf_standard` = `none`/`1.7`/`2.0`/`a-1b`/`a-2b`/`a-3b`/`a-2u`/`a-3u`/`ua-1` (pdf only). `pages` = typst page selection like `1-3,5`, max 40 chars (pdf/svg/png only — not the view 1-20 window). `ppi` 72-300 (png only, default 144). Wrong pairings (`ppi` with pdf, `pdf_standard` with png, …) → `400` before compiling.
- MCP has no per-user export lock (REST `429 Export already running` does not apply); concurrent exports share the 2 compile slots (`503`, §6).
- Report `filename` + `size_bytes` back to the human. Same output as REST `POST /api/docs/{id}/export?format=…` (parity: filename, bytes, magic all match).
