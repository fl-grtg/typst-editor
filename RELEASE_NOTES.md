# Release Notes — `0.2.0rc1` (Prerelease candidate DRAFT, not published)

Additional local changes under review: floating comments avoid the entire marked
source range; all collaborators can propose tracked source changes, including via
MCP `suggest`/`suggestions`; owner/editor acceptance is explicit. Spelling is an
account preference. Image viewing, project file drops, generic attachment upload,
completion refresh, source/preview matching and checkpoint-menu deletion have
been revised. Migrations 20-25 are required. These additions are not a published
release or a completed browser acceptance report.


Status: candidate draft only. Source version is `pyproject.toml` = `0.2.0rc1`.
No tag, no published image/digest, no release date is assigned in this draft.
Final acceptance, CI and image verification remain pending. This draft does
not announce a published or fully verified release.

Build this source candidate locally with
`docker compose -f compose.yml -f compose.prerelease.yml up --build -d`.
The regular `compose.yml` continues to pin the last published stable image;
the override builds `typst-editor:0.2.0rc1` from this checkout. Back up the
data volume in a maintenance window before upgrading. There is no published
candidate digest yet.

## What this candidate contains (implemented, acceptance open)

- Projects-only model: migration 16 auto-converts legacy folders and
  standalone docs; new docs (REST/MCP/ZIP import) get a project immediately.
  Legacy single-doc shares stay doc-scoped (`guest` sees only that doc + its
  reachable sources, never the member list).
- Shared project library without private compile-time fallback; local files win.
  Private → project and project → private transfers are explicit independent
  copies; private originals and project copies count separately toward the owner.
- v19 storage baseline: `users.migration_bytes` is a one-time permanent
  allowance holding the size of the existing project library in bytes at
  migration time (`backend/db.py` `_migrate_v19`). Effective limit is
  `quota.user_cap` = configured cap + `migration_bytes`
  (`backend/services/quota.py`). `GET /api/me` reports
  `storage{used,limit,migration_allowance}` (`backend/routers/auth.py`);
  Settings shows it (`projects.storage` + `projects.migrationAllowance`).
  New copies count normally; the allowance is not re-granted.
- Project titles unique per owner case-insensitive (v19
  `idx_projects_owner_title_nocase`). Create auto-suffixes (`Title (2)`…,
  with a maximum of 100 chars); rename rejects collisions with `409`; existing
  collisions were suffixed once during migration.
- File/resource rename is two-step: `POST /api/projects/{id}/rename-entry-preview`
  returns `{name, version, references}`; `POST /api/projects/{id}/rename-entry`
  requires that `version` (`409` on stale state). The UI shows the static
  references + dynamic-path hint and asks for confirmation; it does not
  rewrite references automatically.
- Removing a project member deletes that member's doc shares in the project and
  wipes all open invites of all project docs (broad revoke, links carry no
  username). The share UI states this broad effect explicitly before confirming
  (`projects.removeMemberWarning`, implemented).
- Project checkpoints (manual + auto, at most every 15 min) with
  `Before restore` copy; manual checkpoints and the creation checkpoint are
  kept forever, automatic checkpoints self-prune to the 10 newest plus one
  per week within 5 weeks (`AUTO_SNAP_KEEP`/`AUTO_SNAP_KEEP_WEEKS`, v25);
  two-stage trash (project archived until its last doc is hard-deleted);
  single worker (`--workers 1`).
- Suggestion/comment reliability: comments and suggestions survive empty-doc
  races and reloads (ranges re-derive after websocket sync); pending
  suggestion matching uses backend semantics; package sessions clamp stale
  positions instead of crashing; changed-package files are painted exactly.
- Suggester staging: packages can stage file adds, deletes and binary
  replaces; deletions land in the project owner's trash only at accept
  time. Review packages by others surface as a topbar badge
  (`GET /api/notifications/summary`) and open the package session directly.
- Robustness: per-owner quota serialization, delta-aware trash restore,
  id-scoped delete rollbacks, request-body cap (32 MB) for API/MCP,
  proposal saves moved out of the write transaction, list endpoints capped
  (`op_suggestions` projection), account rename keeps authored packages
  (FK update, no cascade loss).
- Migrations 20-25 are required (`suggestion_*` columns, `trash_entries`,
  `suggestion_packages`, trash index, snapshot `kind`).

## Breaking changes vs. earlier behavior

- Retired folder routes (`/api/docs/{id}/folder`, `/api/folders…`) and access
  to trashed docs answer `410`.
- Ambiguous legacy MCP titles answer `409`; use
  `/projects/{id}/docs/{Title}`. Doc titles are NOCASE-unique per project;
  project titles are NOCASE-unique per owner.
- No private fallback at compile/export time; document ZIP
  (`main.typ` + `files/…`) and project ZIP
  (`project.json` + `modules/…` + `documents/<id>/main.typ`) are different
  layouts with no full project round-trip promise.
- New writes over quota fail with `413`; over-quota accounts stay
  readable/exportable/deletable until space is freed.
- Stale rename/delete `version` fails with `409`; role/target/trashed mismatches
  fail with defined `403`/`404`/`409` instead of writing stale state.
- Write paths share `files_list`/`mcp`/per-endpoint buckets (`429` without
  mutation); per-user export lock (`429 Export already running`).

## Limits and known boundaries (no full offline/durability promise)

- Live-doc write-behind: nominal ~2 s interval + flush on last disconnect.
  Failed flushes, quota blocks, or load can delay persistence; there is no
  guaranteed loss bound. `saved` means successful server-side store only.
  Side files use version conflicts, no live merge.
- Offline: no full merge. Browser keeps a 24 h local draft with opt-in restore
  (never silent overwrite, no merge guarantee).
- DB dump (`VACUUM INTO`) + files archive are two steps with no shared
  consistent point under writes; use a maintenance window (stop server or no
  writes). The automatic pre-migrate DB backup covers the database only, not
  attachments. Source/project ZIPs are not server backups.
- Default caps: 200000 UTF-8 bytes per doc, 100 chars per
  doc/project title, 10 MB per upload, 200 files per doc, 100 docs + 500 MB per
  user before allowance, 200 KB text resources, 100 MB export cap
  (oversized exports fail; skipped sources are listed where applicable), invites 7 days / max 20 per doc /
  multi-use (token shown once), search min 2 chars / max 20 hits.
- Out of prerelease scope: per-invite attribution, inbox, public read links,
  custom fonts, full offline merge, live editing of all side files, mobile
  rebuild (target is open/correct/save/export on mobile), broad security
  certification.

## Upgrade notes

- Returning DBs migrate through v21 on start (fresh DBs run the same chain).
  v20 adds suggestions and v21 adds the account spelling preference.
  The v19 migration does not block on quota; affected accounts may land over limit
  and then stay readable/exportable/deletable with new writes at `413`.
- Settings and `GET /api/me` show the permanent allowance share; no recurring
  grant for new data and no promise about scope/duration of any future grant.

## Not verified in this draft

- No R1–R6 acceptance is claimed (roles/shares, checkpoints/restore, quota
  races, renames, transfers, import/export, contracts, E2E, compiler-in-CI,
  collab/reconnect, browser walkthrough, backup/restore, install/upgrade,
  load profile, release artefacts).
- No green full-suite, E2E, Docker, load, browser, or restore run is asserted
  for this candidate here; commit/tag/image/digest must be fixed and re-checked
  on the final candidate before any publish.
