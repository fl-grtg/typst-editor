# Contributing

Setup:

python -m venv .venv
pip install -r requirements.txt -r requirements-dev.txt

Check: `pytest -q` (must stay green).

Style: keep it simple, match existing code.
No new frameworks, no extra abstraction layers.

PR steps:

1. Small diff, one topic per PR.
2. Describe what changed and how you tested it.
3. Keep docs short (README stays under 100 lines).
4. Wait for CI green before merge.
5. Keep commits small and reviewable.
6. One review approval merges the PR.
