"""Browser smoke tests (Playwright). Opt-in: skipped unless Playwright + a browser are installed.

    pip install -r requirements-e2e.txt && playwright install chromium
    pytest e2e -q

The live preview loads the Typst compiler from a CDN (until assets are self-hosted),
so these tests need outbound internet access.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def base_url(tmp_path_factory):
    data = tmp_path_factory.mktemp("e2e-data")
    port = _free_port()
    env = {**os.environ, "DATA_DIR": str(data), "REGISTRATION": "open", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while True:
        try:
            with urllib.request.urlopen(url + "/healthz", timeout=1) as r:
                if r.status == 200:
                    break
        except OSError:
            pass
        if proc.poll() is not None or time.monotonic() > deadline:
            out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            proc.kill()
            raise RuntimeError("server did not start:\n" + out[-2000:])
        time.sleep(0.2)
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # browser binary missing
            pytest.skip(f"no Playwright browser available: {e}")
        yield b
        b.close()


@pytest.fixture()
def ctx(browser, base_url):
    c = browser.new_context(base_url=base_url, accept_downloads=True)
    c.set_default_timeout(15_000)
    yield c
    c.close()


@pytest.fixture()
def page(ctx):
    return ctx.new_page()
