# Prerelease validation: 0.2.0rc1

Current local candidate: [merge-readiness.md](merge-readiness.md).

Historical baseline report below. The later local suggestion/editor/upload/spelling
changes (migrations 20/21) are not covered by the pinned commit or baseline test
counts below. Their current checks and blocking Muse review are recorded in the
local-change verification appendix; browser acceptance remains with the user.


Local working-tree candidate based on `8c8bf45`, checked on 16 October 2026.
No commit, tag, publication or candidate image digest has been created.

## Implementation

Project document creation inserts directly into its target namespace. Project
writes have rate limits; document guests cannot obtain the project roster.
Rename previews identify static references and require the reviewed source
version. The UI uses normalized server names, handles missing entries and guides
empty projects through document creation. Member removal explicitly warns that
all project document invitation links will be revoked.

Migration 19 adds case-insensitive project title uniqueness and a permanent,
one-time storage allowance for the existing project library. Settings reports
actual usage, effective limit and allowance. Independent copies still count as
independent data. Account rename preserves the allowance.

Checkpoint capture uses document upload locks and a read transaction, followed
by a short validated database write. A changed database state returns 409.
Restore prepares its file backup before the write transaction and runs in a
worker thread. File publication and database changes still require a serialized
restore operation; this is not a promise of uninterrupted writes during restore.

Live saves check the final text/Yjs quota inside their transaction. An edit
arriving during a flush remains dirty. Text size gates use UTF-8 bytes.

## Completed operational checks

Python 3.11.9, Node 24.15 and Typst CLI 0.15.1 were available on the local
Windows host. The compiler version matches the image pin.

- An isolated server contained three accounts, a project with two documents,
  private and project modules, a binary attachment, project membership,
  document-only sharing and checkpoints. Both documents compiled with Typst.
- With the server stopped, the backup produced a 311296-byte database and a
  331-byte file archive in approximately 0.3 seconds. Restoration into an empty
  data directory passed integrity and foreign-key checks. Roles, modules,
  attachment bytes, checkpoints and source exports survived the restart.
  Both documents compiled again with the same output sizes.
- Upgrade from schema 18 to 19 on an isolated copy succeeded; a second start
  was idempotent. The pre-migration database backup remained at schema 18.
- A small concurrent HTTP profile used five documents, two authenticated
  clients and eight threads. All five saves, five checkpoint operations and
  five source exports succeeded. Exported `main.typ` contents matched saved
  sources. A forced quota boundary returned 413 without changing content or
  checkpoints. Relogin preserved all five document contents.
- A blocked data directory produced the explicit initialization diagnostic.
  The candidate Compose override resolves to a local build of
  `typst-editor:0.2.0rc1`.

The HTTP profile is a functional smoke check, not a capacity benchmark or a
WebSocket reconnect/slow-consumer stress result.

## Candidate checks

The complete backend suite passed 461 tests with no skips and the real Typst
compiler required. Subsequent focused regression runs cover later corrections.
All 55 JavaScript tests, Ruff, Mypy (118 files), generated frontend,
translations and dependency consistency passed. The vendor bundle rebuilt
identically.

Muse Spark 1.3 xhigh (OpenCode) reviewed the complete working-tree changes in
four rounds. Findings from earlier rounds were corrected and re-reviewed;
round four reported no actionable bugs and no blockers. All code changes were
written by the parent agent.

The final full browser run passed all 39 tests (214 seconds). The formerly
intermittent fresh-project Plus-menu regression also passed three separate
runs. Earlier runs exposed stale test assumptions and a sidebar-cache race;
the tests and the actual cache race were corrected before this final run.
The 21 focused prerelease backend regressions passed again afterward.
Another 31 WebSocket, Yjs, quota and duplicate-atomicity tests passed after
the final UTF-8 counter corrections. These final runs used temporary data
directories and produced no new failure artifacts.

## Remaining release gates

- Docker Desktop was started hidden, but the local engine returns HTTP 500;
  its Windows service is stopped and disabled. Image build, fresh container start,
  Compose installation and a full old-image/new-image rollback remain unverified.
- Remote CI and Docker workflows have not run on a committed final candidate.
  Required-check configuration and consecutive green CI runs remain unverified.
- Real mobile devices and the complete supported browser matrix still need
  operator acceptance. A small viewport test alone does not establish that.
- No published digest, signed release or completed release approval is claimed.

Use `docker compose -f compose.yml -f compose.prerelease.yml up --build -d`
to build the candidate from source once Docker is available. Back up the data
volume during a maintenance window first. Restore the matching old database,
files and image for rollback; do not downgrade a migrated database in place.

## Local database side effect

Before the test-import isolation fix, importing the app initialized the local
default `data/app.db` at schema 19. The automatic pre-migration backup is
`data/app-migrate-20261016-040614.db`. `data-dev-projects` remains at schema 18.
The test harness now defaults to a temporary data directory before importing
the application. No local database was automatically rolled back.


## Local-change verification appendix (16 October 2026)

The local candidate adds migrations 20/21, suggestion REST/MCP tools and tracked
editor drafts, floating comment placement, account-wide spelling, generic
attachment upload and image viewing. Earlier baseline counts above do not
certify these additions.

- Python full suite: **505 passed** (`python -m pytest -q`, 499 seconds).
- Nine subsequently added cases passed separately: 3 atomic/empty-document
  suggestion-batch tests, 1 normalized Unicode resource-name API test and
  5 real MCP edit/upload/render/export protocol tests. This covers the current
  514-test collection without claiming a second complete run of all 514.
- Node: **71 passed**, including proposal diff/context, complete-mark comment
  placement, stale image loads, autocomplete and sync regressions.
- Muse Spark 1.3 (OpenCode, xhigh) tested all eleven MCP tools over actual
  `POST /mcp` calls: **17 protocol tests passed**, including real Typst 0.15.1
  PNG/PDF/ZIP output and reviewer permissions. Core proposal tests: **26 passed**.
- Ruff, Mypy, frontend JavaScript syntax, translation parity and generated
  `index.html` freshness checks passed.
- Blocking Muse review covers the entire local diff against main, including
  untracked files, in frontend/backend/integration partitions. Final signoff is
  recorded in the development thread. No browser acceptance, release, commit,
  push, tag or image publication is claimed.
