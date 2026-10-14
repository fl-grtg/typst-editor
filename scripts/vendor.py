#!/usr/bin/env python3
"""Vendor CDN frontend assets into vendor/ with content-hash filenames.

Usage:
    python scripts/vendor.py          # download pinned URLs, write vendor/
    python scripts/vendor.py --check  # verify vendor/ matches manifest (offline)

Sources are the exact pinned URLs used by web/js/00-imports.js and
web/js/50-preview.js. esm.sh entries are mirrored recursively: their
absolute /pkg@ver/... imports are rewritten to relative ./<file> so the
whole closure is self-hosted with one shared copy per module (a single
Yjs instance for yjs + y-websocket matters for sync). Single-file assets
(pdf.js, Typst bundle, WASM) are stored byte-identical.

Output: vendor/<stem>-<sha256[:12]>.<ext> plus vendor/manifest.json
(entry name -> file, and the full servable file list for the backend).
Re-running against the pinned (immutable) URLs reproduces the same names.
Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
MANIFEST = VENDOR / "manifest.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

# (manifest key, source URL, kind, filename stem, extension)
_FONT_BASE = "https://cdn.jsdelivr.net/gh/typst/typst-assets@v0.13.1/files/fonts/"
# Default "text" preload set of the Typst bundle (the only fonts fetched
# unless a doc requests cjk/emoji): runtime behavior stays identical offline.
_FONTS: tuple[str, ...] = (
    "DejaVuSansMono-Bold.ttf", "DejaVuSansMono-BoldOblique.ttf",
    "DejaVuSansMono-Oblique.ttf", "DejaVuSansMono.ttf",
    "LibertinusSerif-Bold.otf", "LibertinusSerif-BoldItalic.otf",
    "LibertinusSerif-Italic.otf", "LibertinusSerif-Regular.otf",
    "LibertinusSerif-Semibold.otf", "LibertinusSerif-SemiboldItalic.otf",
    "NewCM10-Bold.otf", "NewCM10-BoldItalic.otf",
    "NewCM10-Italic.otf", "NewCM10-Regular.otf",
    "NewCMMath-Bold.otf", "NewCMMath-Book.otf", "NewCMMath-Regular.otf",
)
ENTRIES: tuple[tuple[str, str, str, str, str], ...] = (
    ("yjs", "https://esm.sh/yjs@13.6.27", "esm", "yjs-13.6.27", ".js"),
    ("y-websocket", "https://esm.sh/y-websocket@1.5.0?deps=yjs@13.6.27", "esm", "y-websocket-1.5.0", ".js"),
    ("typst", "https://cdn.jsdelivr.net/npm/@myriaddreamin/typst-all-in-one.ts@0.8.0-rc3/dist/esm/index.js",
     "file", "typst-all-in-one-0.8.0-rc3", ".js"),
    ("typst-compiler-wasm",
     "https://cdn.jsdelivr.net/npm/@myriaddreamin/typst-ts-web-compiler@0.8.0-rc3/pkg/typst_ts_web_compiler_bg.wasm",
     "file", "typst-compiler-0.8.0-rc3", ".wasm"),
    ("typst-renderer-wasm",
     "https://cdn.jsdelivr.net/npm/@myriaddreamin/typst-ts-renderer@0.8.0-rc3/pkg/typst_ts_renderer_bg.wasm",
     "file", "typst-renderer-0.8.0-rc3", ".wasm"),
    ("pdf", "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js",
     "file", "pdf-3.11.174", ".min.js"),
    ("pdf-worker", "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js",
     "file", "pdf-worker-3.11.174", ".min.js"),
    ("typstyle-wasm",
     "https://cdn.jsdelivr.net/npm/@typstyle/typstyle-wasm-bundler@0.15.1/typstyle_wasm_bg.wasm",
     "file", "typstyle-wasm-0.15.1", ".wasm"),
    ("typstyle-glue",
     "https://cdn.jsdelivr.net/npm/@typstyle/typstyle-wasm-bundler@0.15.1/typstyle_wasm_bg.js",
     "file", "typstyle-wasm-glue-0.15.1", ".js"),
) + tuple(
    (f"font-{n.rsplit('.', 1)[0].lower()}", _FONT_BASE + n, "file",
     f"font-{n.rsplit('.', 1)[0]}", "." + n.rsplit(".", 1)[1])
    for n in _FONTS
)

_STATIC_IMPORT = re.compile(
    r"(?P<head>(?:import|export)\b[^'\";]*?\bfrom\s*)(?P<q>['\"])(?P<spec>[^'\"]+)(?P=q)")
_SIDE_IMPORT = re.compile(r"(?P<head>import\s*)(?P<q>['\"])(?P<spec>[^'\"]+)(?P=q)")
_DYNAMIC_IMPORT = re.compile(r"(?P<head>import\(\s*)(?P<q>['\"])(?P<spec>[^'\"]+)(?P=q)")
_SOURCEMAP = re.compile(r"^//# sourceMappingURL=\S+\s*$", re.M)
_NON_ALNUM = re.compile(r"[^A-Za-z0-9._-]+")


def _get(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read(), r.url


def _stem_for_origin(url: str) -> str:
    path = urlsplit(url).path.strip("/")
    stem = _NON_ALNUM.sub("-", path).strip("-") or "mod"
    return re.sub(r"-{2,}", "-", stem)[:48].rstrip("-") or "mod"


class Mirror:
    def __init__(self) -> None:
        self.by_url: dict[str, str] = {}  # final URL -> local filename
        self.by_digest: dict[str, str] = {}  # sha256 -> local filename
        self.blobs: dict[str, bytes] = {}  # local filename -> content
        self.active: set[str] = set()

    def store(self, stem: str, ext: str, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        if digest in self.by_digest:
            return self.by_digest[digest]
        name = f"{stem}-{digest[:12]}{ext}"
        if name in self.blobs and self.blobs[name] != data:  # same stem, different bytes
            name = f"{stem}-{digest[:20]}{ext}"
        self.by_digest[digest] = name
        self.blobs[name] = data
        return name

    def mirror_esm(self, url: str) -> str:
        data, final = _get(url)
        if final in self.by_url:
            return self.by_url[final]
        if final in self.active:
            raise SystemExit(f"import cycle at {final}")
        self.active.add(final)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise SystemExit(f"non-text ESM module: {final}") from None

        def repl(m: re.Match[str]) -> str:
            spec = m.group("spec")
            if spec.startswith("./") or spec.startswith("../"):
                local = self.mirror_esm(urljoin(final, spec))
            elif spec.startswith("/") and not spec.startswith("//"):
                local = self.mirror_esm("https://esm.sh" + spec)
            elif spec.startswith("https://esm.sh/"):
                local = self.mirror_esm(spec)
            elif re.match(r"https?:|data:|blob:", spec):
                raise SystemExit(f"external import left in {final}: {spec}")
            else:
                raise SystemExit(f"bare import left in {final}: {spec}")
            return m.group("head") + m.group("q") + "./" + local + m.group("q")

        for pat in (_STATIC_IMPORT, _SIDE_IMPORT, _DYNAMIC_IMPORT):
            text = pat.sub(repl, text)
        text = _SOURCEMAP.sub("", text)
        name = self.store(_stem_for_origin(final), ".js", text.encode("utf-8"))
        self.by_url[final] = name
        self.active.discard(final)
        return name


def build() -> dict[str, object]:
    mirror = Mirror()
    entry: dict[str, str] = {}
    for key, url, kind, stem, ext in ENTRIES:
        if kind == "esm":
            entry[key] = mirror.mirror_esm(url)
        else:
            data, _ = _get(url)
            entry[key] = mirror.store(stem, ext, data)
        print(f"{key} -> {entry[key]}")
    VENDOR.mkdir(exist_ok=True)
    for name, blob in mirror.blobs.items():
        (VENDOR / name).write_bytes(blob)
    manifest: dict[str, object] = {"generated_by": "scripts/vendor.py",
                "entry": entry, "files": sorted(mirror.blobs)}
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stale = [p for p in VENDOR.iterdir()
             if p.is_file() and p.name != MANIFEST.name and p.name not in mirror.blobs]
    for p in stale:
        p.unlink()
        print(f"removed stale {p.name}")
    total = sum(len(b) for b in mirror.blobs.values())
    print(f"wrote {len(mirror.blobs)} files ({total / 1048576:.1f} MiB) + manifest.json")
    return manifest


def check() -> int:
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"manifest unreadable: {e}", file=sys.stderr)
        return 1
    files = manifest.get("files", [])
    entry = manifest.get("entry", {})
    if not isinstance(files, list) or not isinstance(entry, dict):
        print("manifest malformed", file=sys.stderr)
        return 1
    bad = 0
    want = set(files) | set(entry.values())
    for name in sorted(want):
        if not isinstance(name, str):
            print(f"bad manifest entry: {name!r}", file=sys.stderr)
            bad += 1
            continue
        p = VENDOR / name
        if not p.is_file():
            print(f"missing: {name}", file=sys.stderr)
            bad += 1
            continue
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if digest[:12] not in name and digest[:20] not in name:
            print(f"hash mismatch: {name}", file=sys.stderr)
            bad += 1
    if bad:
        return 1
    print(f"vendor/ ok ({len(want)} files)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify vendor/ against manifest (no network)")
    args = ap.parse_args()
    if args.check:
        return check()
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
