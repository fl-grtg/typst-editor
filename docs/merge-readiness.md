# Local merge candidate · 17 October 2026

This report covers the merge candidate on `feature/editor-proposals-ux`.
The historical counts in `prerelease-validation.md` describe earlier candidates.

## Editor experience

- Sidebar entries use one action menu. Project creation stays directly reachable.
- Images, modules, symbols, citations and text color live behind the Insert icon.
  Editor font size uses direct A−/A+ toolbar buttons and remains available in View.
  Formatting remains available in Edit and via shortcuts.
- Narrow windows collapse the main menu and secondary formatting tools.
- The toolbar uses icons; the sidebar names the active draft/package and marks
  the existing changed file rows purple. Only staged files absent from the
  normal tree need separate entries.
  File/package acceptance and package
  deletion share an action menu; original/proposed view and exit remain direct.
- CSV supports cell/block selection, clipboard operations and double-click editing.
- Initial document selection respects navigation already started by the user.
- Binary/text review drafts use IndexedDB with coalesced writes and a legacy
  localStorage fallback. A 4 MB binary draft survived a real browser reload.
- Document-only guests retain document text proposals; project package controls
  are limited to project members.

## Correctness fixes

- Lock objects remain shared while any holder or prospective waiter references
  them; unreferenced locks are reclaimed automatically.
- Legacy unlabeled checkpoints remain protected as manual saves.
- Proposal writes recheck permissions and quota inside the write transaction.
  Add/rename/restore operations enforce the existing filename collision rules.
- Partial acceptance retains only pending changes, including stale siblings.
  Discarding the final pending change can save an empty correction and exit.
- Failed undo snapshots or broadcasts after acceptance cannot report a failed
  mutation or leave the live document behind the committed database state.
- Review uploads remain staged. Proposal mode becomes available after the
  document's initial synchronization; stale providers cannot open its write gates.
- New text proposals rebase onto independently changed originals at submission.
  Actual overlapping conflicts preserve the draft and explain the problem in the
  selected language. Missing attachment cleanup rechecks transaction permissions.
- Proposal marks and gutter markers wait until the matching editor buffer is
  installed. Opening a longer proposal from an empty document no longer paints
  positions into the empty transition state. A browser regression checks the
  cross-document review, exit, and resource mode toggle without page errors.
- Leaving proposal mode restores the active file without reopening its host
  document. Resource files retain their file view; font controls remain visible.
- Rebase rejects already-applied insertions and newly overlapping anchors as
  conflicts, avoiding duplicated text. The taller header also clears Settings.
- Existing saved proposals with repeated CSV anchors render from their complete
  before/after snapshots instead of failing to open. Newly generated proposals
  extend context across overlapping repetitions. The author can view and withdraw
  a repetitive CSV proposal without changing the saved source.

## Verification

- Earlier complete backend run: 567 passed. Later focused proposal regressions:
  18 passed, including preserved independent edits, genuine conflicts, already
  applied insertions and overlapping anchors. File permission regressions: 9 passed.
- JavaScript: 139 passed. Ruff, full Mypy (132 files), 701-key translation parity,
  generated frontend and Python dependency consistency passed.
- Earlier complete Chromium run: 43 passed. Later combined transition/dialog run:
  11 passed. Latest complete clean-editor run: 8 passed in 46.07 seconds, including
  the real repetitive-CSV view/withdraw flow and the 4 MB reload/restore flow.
- IndexedDB write transactions now require strict durability. The editor suite
  passed twice after that change, including the final run without instrumentation.
- GLM 5.3 Flash Free (OpenCode, max) reviewed the full frontend/backend and the
  correction rounds. All concrete earlier findings were corrected. Transition,
  font and rebase corrections were approved; its minor offline-exit finding is
  fixed. The final sidebar/CSV and storage durability checks remain in progress.
- CI and container validation will run on the PR. Earlier local Docker checks
  could not use an available engine; no container success is claimed locally.
- PR CI exposed a proposal-start timing race: typing before the async mode
  transition completed could edit the source. Startup now holds the editor
  read-only and disables the toggle until ready, with document/epoch checks.
  A deliberately delayed membership response verifies source isolation. This
  regression and the original failing CI test passed locally (2 tests, 10.54 s);
  all 139 JavaScript tests, Ruff and full Mypy passed after the correction.

## User acceptance

Dev server: http://127.0.0.1:8979/?lang=de

Test account: `test` / `12345678`. Data directory: `data-dev-merge`, independent
of the existing server on port 8978. The user authorized a PR and CI/container
validation; merging remains gated on the user's final review.
`Editor Demo` contains two documents, shared Typst/CSV/Bib/JSON modules, an image
and a pending review package. `test2` / `12345678` is its reviewer. The report's
real Typst PDF export succeeded (21,107 bytes).

Container build and remote CI are not certified by the local checks. Docker's
local engine was unavailable when checked. Real-device/browser-matrix acceptance
remains separate from the automated Chromium tests.
