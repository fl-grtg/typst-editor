#!/usr/bin/env python3
"""Assemble the single-file frontend (index.html) from web/ sources.

Usage:
    python web/build.py            # write index.html
    python web/build.py --check    # exit 1 if index.html is out of date (CI)

The shell (web/index.shell.html) contains lines of the form
``@@include css/00-tokens.css@@``; each is replaced verbatim by that file's
content. ``@@include-glob js/features/*.js@@`` inlines every matching file
(sorted, verbatim, so later tracks never touch the shell). ``@@i18n@@`` is
replaced by one <script type="application/json"> tag merging
web/i18n/<lang>/<area>.json, or by nothing when web/i18n/ is absent.
Stdlib only, no Node needed at build or run time.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent
OUT = WEB.parent / "index.html"
SHELL = WEB / "index.shell.html"
MARK = re.compile(r"^@@include ([\w./-]+)@@\n", re.M)
GLOB_MARK = re.compile(r"^@@include-glob ([\w./*?-]+)@@\n", re.M)
I18N_MARK = re.compile(r"^@@i18n@@\n", re.M)


def _read(p: Path) -> str:
    with p.open(encoding="utf-8", newline="") as f:
        return f.read()


def _i18n_tag() -> str:
    # Minimal hook for track 1B: merge web/i18n/<lang>/<area>.json into the
    # page as {"<lang>": {"<area>": {...}}}. Absent dir -> empty (skip
    # silently); broken JSON -> loud failure with the filename.
    base = WEB / "i18n"
    if not base.is_dir():
        return ""
    merged: dict[str, dict[str, object]] = {}
    for p in sorted(base.glob("*/*.json")):
        try:
            data = json.loads(_read(p))
        except ValueError as e:
            raise SystemExit(f"i18n: invalid JSON in {p.relative_to(WEB)}: {e}") from e
        merged.setdefault(p.parent.name, {})[p.stem] = data
    payload = json.dumps(merged, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")
    return f'<script id="i18n-data" type="application/json">{payload}</script>\n'


def build() -> str:
    def sub(m: re.Match[str]) -> str:
        p = (WEB / m.group(1)).resolve()
        if WEB not in p.parents:
            raise SystemExit(f"include escapes web/: {m.group(1)}")
        if not p.is_file():
            raise SystemExit(f"include not found: {m.group(1)}")
        return _read(p)

    def sub_glob(m: re.Match[str]) -> str:
        parts = []
        for p in sorted(WEB.glob(m.group(1))):
            if WEB not in p.resolve().parents or not p.is_file():
                continue
            t = _read(p)
            parts.append(t if t.endswith("\n") else t + "\n")
        return "".join(parts)

    out = MARK.sub(sub, _read(SHELL))
    out = GLOB_MARK.sub(sub_glob, out)
    return I18N_MARK.sub(lambda _: _i18n_tag(), out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if index.html differs from the build")
    args = ap.parse_args()
    built = build()
    if args.check:
        if not OUT.is_file() or _read(OUT) != built:
            print("index.html is out of date - run: python web/build.py", file=sys.stderr)
            return 1
        print("index.html is up to date")
        return 0
    with OUT.open("w", encoding="utf-8", newline="") as f:
        f.write(built)
    print(f"wrote {OUT.name} ({len(built.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
