"""1E: self-hosted vendor assets are served; the page needs no external CDN."""
import json
import re
from pathlib import Path

from backend import deps

ROOT = Path(__file__).resolve().parent.parent
VENDOR_URL = re.compile(r"/vendor/([A-Za-z0-9._-]+)")


def _page_urls() -> list[str]:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    return sorted(set(VENDOR_URL.findall(html)))


def test_vendor_manifest_matches_disk():
    manifest = json.loads((ROOT / "vendor" / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["entry"]) >= {"yjs", "y-websocket", "typst", "typst-compiler-wasm",
                                      "typst-renderer-wasm", "pdf", "pdf-worker"}
    assert set(manifest["files"]) >= set(manifest["entry"].values())
    for name in manifest["files"]:
        assert re.search(r"-[0-9a-f]{12,}\.", name), f"no content hash: {name}"
        assert (ROOT / "vendor" / name).is_file(), f"missing: {name}"
    assert set(deps.VENDOR_FILES) == set(manifest["files"])


def test_vendor_page_urls_served_immutable(c):
    names = _page_urls()
    manifest = json.loads((ROOT / "vendor" / "manifest.json").read_text(encoding="utf-8"))
    for name in manifest["entry"].values():  # every primary asset is referenced by the page
        assert name in names, name
    for name in names:
        r = c.get(f"/vendor/{name}")
        assert r.status_code == 200, name
        assert r.headers.get("cache-control") == "public, max-age=31536000, immutable", name
    js = c.get("/vendor/" + next(n for n in names if n.startswith("yjs-13")))
    assert "text/javascript" in js.headers.get("content-type", "")
    wasm_names = [n for n in names if n.endswith(".wasm")]
    assert len(wasm_names) == 2
    for name in wasm_names:
        assert "wasm" in c.get(f"/vendor/{name}").headers.get("content-type", ""), name


def test_vendor_unknown_is_404(c):
    assert c.get("/vendor/nope-1234.js").status_code == 404
    assert c.get("/vendor/manifest.json").status_code == 404
    assert c.get("/vendor/../index.html").status_code in (404, 307, 308)


def test_no_cdn_hosts_in_built_page():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for token in ("esm.sh", "jsdelivr", "cdnjs", "unpkg"):
        assert token not in html, token


def test_csp_self_hosted_only(c):
    csp = c.get("/").headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    for token in ("esm.sh", "jsdelivr", "cdnjs.cloudflare"):
        assert token not in csp, token
