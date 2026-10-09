#!/usr/bin/env python3
"""Assemble the single-file frontend (index.html) from web/ sources.

Usage:
    python web/build.py            # write index.html
    python web/build.py --check    # exit 1 if index.html is out of date (CI)

The shell (web/index.shell.html) contains lines of the form
``@@include css/00-tokens.css@@``; each is replaced verbatim by that file's
content. Stdlib only, no Node needed at build or run time.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent
OUT = WEB.parent / "index.html"
SHELL = WEB / "index.shell.html"
MARK = re.compile(r"^@@include ([\w./-]+)@@\n", re.M)


def _read(p: Path) -> str:
    with p.open(encoding="utf-8", newline="") as f:
        return f.read()


def build() -> str:
    def sub(m: re.Match[str]) -> str:
        p = (WEB / m.group(1)).resolve()
        if WEB not in p.parents:
            raise SystemExit(f"include escapes web/: {m.group(1)}")
        if not p.is_file():
            raise SystemExit(f"include not found: {m.group(1)}")
        return _read(p)

    return MARK.sub(sub, _read(SHELL))


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
