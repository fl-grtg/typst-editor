import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_sw_version_format():
    sw = (ROOT / "sw.js").read_text()
    assert re.search(r"const V = 'typst-\d+'", sw), "sw.js V must be 'typst-N'"


def test_sw_shell_files_exist():
    sw = (ROOT / "sw.js").read_text()
    m = re.search(r"SHELL = \[(.*?)\]", sw, re.S)
    assert m, "SHELL list missing in sw.js"
    for entry in re.findall(r"'([^']+)'", m.group(1)):
        p = (ROOT / entry.lstrip("./")).resolve() if entry != "./" else ROOT / "index.html"
        assert p.exists(), f"sw.js SHELL entry missing: {entry}"
