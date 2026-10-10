"""Wave 2B (Editor): formatter corpus + vendor wiring.

Split coverage (honest): this file checks everything checkable without a
browser — corpus presence, the vendored typstyle asset, and the build hook.
Live behavior (format shortcut formats, double format is stable, the
formatted doc still renders) runs in e2e/test_wave2b_editor.py with the
real WASM formatter. Corpus compile runs here when the typst CLI exists,
otherwise it is skipped (same pattern as test_real_typst_pdf).
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import web.build as build

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"


def _fixtures() -> list[Path]:
    files = sorted(FIX.glob("*.typ"))
    assert len(files) >= 3, "formatter corpus missing in tests/fixtures/"
    return files


def test_corpus_present_and_nontrivial():
    for p in _fixtures():
        text = p.read_text(encoding="utf-8")
        assert len(text.strip()) > 50, p.name
        assert text.endswith("\n"), p.name


def test_typstyle_vendor_wired():
    manifest = json.loads((ROOT / "vendor" / "manifest.json").read_text(encoding="utf-8"))
    for key in ("typstyle-wasm", "typstyle-glue"):
        assert key in manifest["entry"], key
        name = manifest["entry"][key]
        assert re.search(r"-[0-9a-f]{12,}\.", name), f"no content hash: {name}"
        assert (ROOT / "vendor" / name).is_file(), f"missing: {name}"
    wasm = (ROOT / "vendor" / manifest["entry"]["typstyle-wasm"]).read_bytes()
    assert wasm[:4] == b"\0asm", "not a WebAssembly module"
    assert len(wasm) < 1024 * 1024, f"typstyle wasm too big: {len(wasm)}"
    glue = (ROOT / "vendor" / manifest["entry"]["typstyle-glue"]).read_text(encoding="utf-8")
    assert "export function format(" in glue
    assert "__wbg_set_wasm" in glue
    assert "jsdelivr" not in glue and "esm.sh" not in glue and "http" not in glue.split("export")[0]


def test_build_hook_resolves_typstyle_urls():
    html = build.build()
    assert "@@typstyle" not in html
    manifest = json.loads((ROOT / "vendor" / "manifest.json").read_text(encoding="utf-8"))
    for key in ("typstyle-wasm", "typstyle-glue"):
        assert ("/vendor/" + manifest["entry"][key]) in html, key
    for token in ("esm.sh", "jsdelivr", "cdnjs", "unpkg"):
        assert token not in html, token


def test_corpus_compiles_with_real_cli(tmp_path):
    exe = shutil.which("typst")
    if not exe:
        import pytest

        pytest.skip("typst CLI missing")
    for p in _fixtures():
        out = tmp_path / (p.stem + ".pdf")
        r = subprocess.run([exe, "compile", str(p), str(out)],
                           capture_output=True, timeout=60)
        assert r.returncode == 0, f"{p.name}: {r.stderr.decode()[-500:]}"
        assert out.is_file() and out.stat().st_size > 0, p.name
