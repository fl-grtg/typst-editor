## What and why

<!-- What changed and why. Link the issue if there is one (e.g. "Closes #123"). -->

## Screenshots

<!-- Optional. Before/after for visible UI changes. Delete if not applicable. -->

## Change size

<!--
Totals from `git diff --stat` by area, e.g. "3 files, +120 / -18".
Remove rows that do not apply. Keep the Total row.
-->

| Area | Files | Lines (+/-) |
| --- | --- | --- |
| Code (frontend + backend) | | |
| E2E (`e2e/`) | | |
| Tests (`tests/`) | | |
| Docs/README | | |
| Other | | |
| **Total** | | |

## Checklist

<!-- Check only what you actually did. Do not edit the lines. -->

- [ ] `make check` passes (lint, types, tests, frontend build check)
- [ ] Tests added or updated for behaviour changes
- [ ] If `web/` changed: `index.html` regenerated with `python web/build.py`
- [ ] Database changes are a new append-only migration
- [ ] Docs/README updated if needed
