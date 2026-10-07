---
name: typst-editor
description: Self-hosted Typst docs via MCP (ls, read, create, edit, view, export, search, upload, comment). Use for /docs, /shared, /templates work through the typst-editor server.
---

# Typst Editor — MCP Agent Skill

Work on the user's self-hosted Typst docs through MCP (Streamable HTTP).

## 0. Human setup (once — walk the user through this if anything is missing)

1. Server URL: local `http://127.0.0.1:8978` (from this checkout: `docker compose up -d`, port via `PORT`; image `ghcr.io/fl-grtg/typst-editor:main`) or remote `https://host`. The user needs an account on it — server default is `invite-only`, so an invite code (or the admin) may be required first; `closed` needs the admin (set `REGISTRATION`, no UI for it), no self-registration. Fresh Docker installs print the token once on first start (`docker compose logs app | grep "invite code"`; also stored `chmod 600` as `DATA_DIR/.invite_token`).
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
| `ls(path="/")` | `/`, `/docs`, `/shared`, `/templates`, or a doc path (its files) |
| `read(path, offset=1, limit=0)` | line window over doc / text file / template (offset 1-based, limit 0 = all, past-the-end → `""`) → `content` + echoed `offset` + `total_lines` + `last_seen` (pass to `edit`) |
| `create(path, content="")` | new doc, file, or template (needs `.typ` suffix, else `404`). `400` if it exists; binary names need `upload` instead |
| `edit(path, old_string, new_string, replace_all=false, last_seen=null)` | anchor edit (§5), max 200_000 chars |
| `search(query)` | doc main text (titles + content, no files/templates), min 2 chars, max 20 hits |
| `upload(path, content_base64, filename=null)` | attachment (`…/{File}` or doc + `filename`), max 10 MB |
| `comment(path, anchor, text, quote="", parent_id=null)` | `anchor` = 1-based line number (`1` = first line, max 10M; `0` is accepted as an alias for `1`); text ≤2000 chars; **docs only** (file/template paths → `400`); one reply level; create-only, rest in UI |
| `view(path, pages="1-5", scale=1.0)` | doc pages as viewable image blocks (longest side ≤1280px) → image blocks + `count` + `total_pages` + `cache_hit` + `last_seen`; pages format `"2"`, `"1-5"`, `"6-10"`, `"1-3,5"` — numbers 1-20, max 20 per call; `scale` 0.5-3.0 (default 1.0 → 144 ppi). Compile errors → `422` with `diagnostics: [{file, line, col, message}]`. No manual decode needed — see §8 |
| `export(path, format="pdf")` | doc as file → `format` + `mime` + `filename` + `content_base64` + `size_bytes`. Formats: `pdf` (full multi-page PDF), `svg`/`png` (single page directly, multi-page docs arrive as ZIP of `page-{n}` files), `zip` (source bundle: `main.typ` + `files/…` + `SKIPPED.txt` if oversized). Read-only: reviewer keys work. Always decode + save, see §9 |

## 4. Paths

- `/docs/{Title}` = doc (readable AND its file list; `ls` a file or template path → `400`, use `read`), `/docs/{Title}/{File}` = text/attachment
- `/shared/{Owner}/{Title}[/{File}]` = shared with the key owner
- `/templates/{Name}.typ` = reusable template
- `/` inside a title breaks the path → such titles are unreachable (`400` at create)

## 5. Edit rules

- `old_string` required, 2–3 lines of context, copied from `read` — never guessed.
- `0` matches → `409 anchor-gone`: re-`read`, then retry with a bigger anchor.
- `>1` matches → `409 anchor-ambiguous`: add context, or `replace_all=true` (renames).
- `last_seen` is optional: stale marker + clean anchor still applies (returns `stale: true`).
- Binary `read` → `400`: `view` the parent doc (renders only embedded content), `upload` to replace the file.

## 6. On errors

- `404` → path is wrong or renamed: `ls` the parent again, never retry blindly.
- `403` → missing right: ask the human for a share (or a stronger key). Reviewer keys/shares are read + comment only — that is the minimum of key role and share role. Rename/share/delete/invite/resolve don't exist as MCP tools — human in the UI.
- `410` → doc is trashed: tell the human to restore it in the UI.
- `429` → rate limit (60/min): back off, don't retry-loop. REST export of the same doc also serializes per user (`429 Export already running`) — wait, then retry once.
- `export` errors: bad `format` or file/template path → `400`; unknown doc → `404`; compile errors → `422` with `diagnostics` (same shape as `view`: fix the quoted line, re-export); source/output over 100 MB → `413`; missing `typst` CLI or 30s timeout → `500`.

## 7. Limits

- `search` <2 chars: no hits. `upload`: 200 files/doc, 500 MB/user. Text: max 200_000 chars (`create`/`edit` fail above). `view`: needs the `typst` CLI on the server (Docker image has it).
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
- `zip` format is sources, not renderings: `main.typ` + `files/{name}` (+ `SKIPPED.txt` listing oversized attachments left out). Use it to hand the human the editable bundle.
- Report `filename` + `size_bytes` back to the human. Same output as REST `POST /api/docs/{id}/export?format=…` (parity: filename, bytes, magic all match).
