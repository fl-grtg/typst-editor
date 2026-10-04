---
name: typst-editor
description: Self-hosted Typst docs via MCP (ls, read, edit, view, search, upload, comment). Use for /docs, /shared, /templates work through the typst-editor server.
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
ls -> read -> edit -> view -> fix
```

Copy paths from `ls` output, never invent them.

## 3. Tools

| Tool | Does |
| --- | --- |
| `ls(path="/")` | `/`, `/docs`, `/shared`, `/templates`, or a doc path (its files) |
| `read(path)` | doc / text file / template → `content` + `last_seen` (pass to `edit`) |
| `create(path, content="")` | new doc, file, or template (needs `.typ` suffix, else `404`). `400` if it exists; binary names need `upload` instead |
| `edit(path, old_string, new_string, replace_all=false, last_seen=null)` | anchor edit (§4), max 200_000 chars |
| `search(query)` | doc main text (titles + content, no files/templates), min 2 chars, max 20 hits |
| `upload(path, content_base64, filename=null)` | attachment (`…/{File}` or doc + `filename`), max 10 MB |
| `comment(path, anchor, text, quote="", parent_id=null)` | `anchor` = line number (`0` = top, max 10M); text ≤2000 chars; **docs only** (file/template paths → `400`); one reply level; create-only, rest in UI |
| `view(path, pages="1-5")` | doc pages as base64 PNG (≤1024px) → `pages` + `count` + `cache_hit` + `last_seen`; `"2"`, `"1-3"` work, max 5 |

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
- `429` → rate limit (60/min): back off, don't retry-loop.

## 7. Limits

- `search` <2 chars: no hits. `upload`: 200 files/doc, 500 MB/user. Text: max 200_000 chars (`create`/`edit` fail above). `view`: needs the `typst` CLI on the server (Docker image has it).
