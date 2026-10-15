"""Overhaul export sources: unified closure, root-renderable ZIPs, backup bundles."""
import base64
import io
import shutil
import subprocess
import zipfile

import pytest
from conftest import make_doc, register_user


def _res(c, name, content="#x", folder=""):
    return c.post("/api/templates", json={"name": name, "content": content, "folder": folder})


def _typst():
    return shutil.which("typst")


def _bundle(c, title="Exp"):
    """Doc with nested attachment importing global resources + csv (transitive)."""
    register_user(c, "own")
    _res(c, "base.typ", "#let base = [BASE]")
    _res(c, "lib.typ", '#import "base.typ": base\n#let hi(name) = [Hi #name (#base)]')
    _res(c, "data.csv", "name,score\nAda,100")
    did = make_doc(c, title=title,
                   content='#import "lib.typ": hi\n#include "sub/part.typ"\n= Title\nMain: #hi("main").')
    r = c.post(f"/api/docs/{did}/files/sub/part.typ/text",
               json={"content": '#import "../lib.typ": hi\n#let rows = csv("../data.csv")\n'
                                'Part: #hi("nested") n=#rows.len().'})
    assert r.status_code == 200, r.text
    pid = c.get(f"/api/docs/{did}").json()["project_id"]
    body = {"source_scope": "personal", "source": "data.csv", "scope": "project", "project_id": pid, "name": "data.csv"}
    p = c.post("/api/library/pull-preview", json=body)
    assert p.status_code == 200, p.text
    assert c.post("/api/library/pull", json={**body, "preview": p.json()["preview"]}).status_code == 200
    return did


def test_source_zip_root_paths_and_closure(c):
    did = _bundle(c)
    r = c.post(f"/api/docs/{did}/export", params={"format": "zip"})
    assert r.status_code == 200, r.text
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "main.typ" in names
    assert "sub/part.typ" in names  # nested path preserved
    assert "lib.typ" in names  # direct resource
    assert "base.typ" in names  # transitive through the shelf
    assert "data.csv" in names  # csv resource via nested relative ref
    assert not any(n.startswith("files/") for n in names)


def test_source_zip_compiles_with_real_typst(c, tmp_path):
    if not _typst():
        pytest.skip("typst CLI missing")
    did = _bundle(c, title="RealZip")
    r = c.post(f"/api/docs/{did}/export", params={"format": "zip"})
    assert r.status_code == 200, r.text
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    zipfile.ZipFile(io.BytesIO(r.content)).extractall(bundle)
    assert (bundle / "main.typ").is_file()
    assert (bundle / "sub" / "part.typ").is_file()
    p = subprocess.run([_typst(), "compile", "main.typ", "out.pdf"],
                       cwd=bundle, capture_output=True, timeout=60)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")[-1000:]
    pdf = bundle / "out.pdf"
    assert pdf.is_file() and pdf.read_bytes()[:5] == b"%PDF-"


def test_rest_mcp_export_parity(c):
    import asyncio

    from backend import mcp_tools as _mt

    did = _bundle(c, title="Parity")
    r = c.post(f"/api/docs/{did}/export", params={"format": "zip"})
    assert r.status_code == 200, r.text
    rest_names = sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    out = asyncio.run(_mt.op_export("own", "owner", "/docs/Parity", "zip"))
    mcp_names = sorted(zipfile.ZipFile(io.BytesIO(base64.b64decode(out["content_base64"]))).namelist())
    assert mcp_names == rest_names
    assert "lib.typ" in mcp_names and "base.typ" in mcp_names


def test_view_includes_resources(c):
    import asyncio

    from backend import mcp_tools as _mt

    if not _typst():
        pytest.skip("typst CLI missing")
    _bundle(c, title="ViewRes")
    out = asyncio.run(_mt.op_view("own", "owner", "/docs/ViewRes", "1"))
    sc = out.structured_content
    assert sc["count"] >= 1  # compiles with the closure (missing lib.typ would 422)


def test_full_backup_per_doc_closure(c):
    did = _bundle(c, title="Bak")
    r = c.get("/api/export.zip")
    assert r.status_code == 200, r.text
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "templates/lib.typ" in names  # global shelf organization kept
    assert "templates/data.csv" in names
    # Per-doc bundle carries nested paths + the resource closure.
    assert any(n.endswith("Bak-files/sub/part.typ") for n in names), names
    assert any(n.endswith("Bak-files/lib.typ") for n in names), names
    assert any(n.endswith("Bak-files/base.typ") for n in names), names
    assert not any("Bak-files/files/" in n for n in names)
    _ = did
