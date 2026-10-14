# Contributing

Thanks for helping! This project aims to stay small enough to read in one sitting, so please keep changes focused.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
make dev          # runs the app on http://127.0.0.1:8978 with ./data
make check        # lint + type check + tests + frontend build check
```

`make help` lists all targets.

## Repository layout

| Path | What lives there |
|---|---|
| `backend/main.py` | App factory: lifespan, middleware, exception handlers, router registration |
| `backend/routers/` | HTTP/WebSocket endpoints, one module per area (`auth`, `docs`, `files`, `share`, ...) |
| `backend/deps.py`, `backend/services/` | Shared helpers: auth dependency, access checks, locks, quota, snapshots, ... |
| `backend/schemas.py` | Request models |
| `web/` | **Source of the frontend** (see `web/README.md`) |
| `index.html` | Generated single-file frontend, committed. Do not edit by hand |
| `cm-build/`, `vendor-cm.js` | CodeMirror bundle and its build |
| `tests/` | Backend tests (`pytest`) |
| `e2e/` | Browser smoke tests (Playwright, opt-in, not part of the default `pytest` run) |

## Frontend changes

Edit files under `web/` (CSS in `web/css/`, JavaScript in `web/js/`, markup in `web/index.shell.html`), then:

```bash
python web/build.py          # regenerate index.html
python web/build.py --check  # what CI runs
```

Commit the regenerated `index.html` together with your source change.

## Tests

```bash
pytest -q                    # backend tests, no browser needed
pip install -r requirements-e2e.txt && playwright install chromium
pytest e2e -q          # browser smoke tests (need outbound internet for the Typst compiler CDN)
```

Every behaviour change needs a test. Bug fixes should come with a regression test.

## Style

- Code, comments, commit messages, docs and UI strings are **English**.
- Python: `ruff check` and `mypy` must pass (see `pyproject.toml`). Formatting is not enforced.
- Keep modules under ~600 lines; split by responsibility rather than growing a file.
- Database changes are **append-only migrations** (`_migrate_vN` at the end of `backend/db.py`), never edits to old ones.
- No new runtime dependencies without discussion; the default deployment stays one container.

## Pull requests

1. Open an issue first for larger changes or new features.
2. Keep the PR small and focused; describe the *why*.
3. Make sure `make check` passes.
4. Security problems: **do not** open a PR or issue, see [SECURITY.md](SECURITY.md).

By contributing you agree that your contribution is licensed under the project's Apache-2.0 license.
Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).
