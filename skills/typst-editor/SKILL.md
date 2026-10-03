# Typst Editor — MCP Agent Skill

Access the self-hosted Typst editor through Model Context Protocol (MCP).

## Connect

- Endpoint (Streamable HTTP): `http://127.0.0.1:8978/mcp` (host/port varies — substitute as needed)
- Auth: `Authorization: Bearer tpe_<prefix>_<secret>` header only. No cookie needed.
- Create the key in the Settings UI (web login). The secret is shown **once** — store it immediately.
- Tool errors arrive as `isError: true` at HTTP 200 (not as HTTP status codes).

## Setup (register the server in your client)

Claude Code:

```
claude mcp add --transport http typst-editor http://127.0.0.1:8978/mcp \
  --header "Authorization: Bearer tpe_<prefix>_<secret>"
```

OpenCode (`opencode.json`):

```json
{
  "mcp": {
    "typst-editor": {
      "type": "remote",
      "url": "http://127.0.0.1:8978/mcp",
      "headers": { "Authorization": "Bearer tpe_<prefix>_<secret>" }
    }
  }
}
```

## Workflow loop

```
ls -> read -> edit -> view -> fix
```

1. `ls` for an overview (docs, shared, templates, or files inside a doc).
2. `read` the target file (`last_seen` marker is returned — pass it to `edit`; optional, but recommended).
3. `edit` with a precise anchor (see rules below).
4. `view` to render pages as PNG and check the result.
5. Fix and re-view until correct.

## Tools

- `ls(path="/")` — browse `/`, `/docs`, `/shared`, `/templates`, or a document path (files).
- `read(path)` — doc, text file, or template. Returns `content` + `last_seen`.
- `create(path, content="")` — doc `/docs/{Title}`, text file `/docs/{Title}/{File}`, or template. Fails with `400` if it exists. Binary names need `upload` instead.
- `edit(path, old_string, new_string, replace_all=false, last_seen=null)` — anchor edit, see rules.
- `search(query)` — titles + content (at most 20 hits).
- `upload(path, content_base64, filename=null)` — attachment: `/docs/{Title}/{File}` or `/docs/{Title}` + `filename`. Max 10 MB.
- `comment(path, anchor, text, quote="", parent_id=null)` — `anchor` is a line number (0 = start). Create-only.
- `view(path, pages="1-5")` — renders pages 1–5 as base64 PNGs (width ≤1024px). Returns `pages` + `count` + `cache_hit` + `last_seen`.

## Path model

- `/docs/{Title}` — a document
- `/docs/{Title}/{File}` — a text file or attachment inside a document
- `/shared/{Owner}/{Title}[/{File}]` — docs shared with the key owner
- `/templates/{Name}.typ` — reusable templates
- A `/` inside a title splits the path, so titles with `/` can't be addressed (400).

## Edit rules

- `old_string` is required, with 2–3 lines of context around the change.
- `0` matches → `409 anchor-gone`: re-read first, the content changed.
- `>1` matches → `409 anchor-ambiguous`: add more context or use `replace_all=true`.
- `replace_all=true` replaces every match.
- `last_seen` from `read` is optional: without it the edit still runs; a stale marker with a clean anchor proceeds (returned as `stale: true`, not an error).
- `create` on an existing title fails with `400`.
- Binary `read` fails with `400`: use `view` to render it, `upload` to replace it.
- `view` renders at most 5 pages per call.

## Permissions

- Reviewer keys (and reviewer shares) are read + comment only — edits return `403`.
- Effective rights are the minimum of key role and share role.
- Owner/Admin stays in the human UI.
- Comments via tools are create-only; edit/delete/resolve happens in the UI
  (comments are author-only for edit; delete/resolve additionally allows the doc owner).

## Limits

- `search` queries shorter than 2 chars return no hits; at most 20 hits.
- `upload` max 10 MB per file, 200 files per doc, 500 MB per user.
- `view` pages `1-5` only (e.g. `pages: "2"` for a single page).
- MCP calls are rate-limited (60/min per key) — slow down on `429`.
- `ls` targets: `/`, `/docs`, `/shared`, `/templates`, or a document path (files).
