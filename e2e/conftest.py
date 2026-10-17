"""Browser regression fixtures using a temporary database and self-hosted assets.

Playwright and Chromium must be installed; missing browser dependencies fail
instead of silently skipping CI coverage. No production or dev-project data is used.
"""
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

expect.set_options(timeout=15_000)  # assertion waits match the ctx action timeout (expect default is only 5s)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, 'rep_' + report.when, report)

ROOT = Path(__file__).resolve().parents[1]

_SERVER_LOG_PATH: Path | None = None


def _server_tail(n: int = 100) -> str:
    try:
        if _SERVER_LOG_PATH is None or not _SERVER_LOG_PATH.exists():
            return "<no server log>"
        lines = _SERVER_LOG_PATH.read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError as e:
        return f"<server log unreadable: {e}>"


def pytest_runtest_logreport(report):
    if report.when == "call" and report.failed:
        tail = _server_tail(100)
        print(f"\n[server-log-tail last 100 lines]\n{tail}\n[/server-log-tail]")
        try:
            report.sections.append(("server log tail", tail))
        except Exception:
            pass


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def base_url(tmp_path_factory):
    global _SERVER_LOG_PATH
    data = tmp_path_factory.mktemp("e2e-data")
    port = _free_port()
    env = {**os.environ, "DATA_DIR": str(data), "REGISTRATION": "open", "PYTHONUNBUFFERED": "1",
           # All smoke tests share one egress IP, hence one per-IP rate-limit bucket
           # (production clients have distinct IPs). Raise the chatty list/poll
           # budget so the suite can't 429 itself; app limits stay untouched.
           "RATE_FILES_LIST_PER_MIN": "1000", "RATE_SIDEBAR_PER_MIN": "1000", "RATE_REGISTER_PER_HOUR": "1000"}
    _SERVER_LOG_PATH = data / "server.log"
    # NOTE: never stdout=PIPE here without a reader: once the pipe buffer
    # (64KB on GH runners) fills, uvicorn blocks on its next access-log
    # write and the server hangs (late-test page.goto timeouts). A file
    # never blocks and keeps the log for the failure tail below.
    logf = open(_SERVER_LOG_PATH, "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT,
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
            try:
                logf.flush()
                out = _SERVER_LOG_PATH.read_text(errors="replace") if _SERVER_LOG_PATH else ""
            except OSError:
                out = ""
            proc.kill()
            logf.close()
            raise RuntimeError("server did not start:\n" + out[-2000:])
        time.sleep(0.2)
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    finally:
        logf.close()


@pytest.fixture()
def browser():
    # NOTE: function-scoped (fresh browser per test, not per session): a
    # session-shared browser accumulates WASM/compiler/canvas memory across
    # contexts and late-suite navigations stall past the 15s goto timeout
    # even with a healthy server (CI test_6, local 8th-navigation retries).
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # browser binary missing
            pytest.fail(f"no Playwright browser available: {e}")
        yield b
        b.close()


@pytest.fixture()
def ctx(browser, base_url, request):
    c = browser.new_context(base_url=base_url, accept_downloads=True, locale="en-US")
    c.set_default_timeout(15_000)
    c.tracing.start(screenshots=True, snapshots=True, sources=True)
    yield c
    if getattr(request.node, 'rep_call', None) and request.node.rep_call.failed:
        dest = ROOT / 'test-results' / re.sub(r'[^A-Za-z0-9_-]', '_', request.node.nodeid)
        dest.mkdir(parents=True, exist_ok=True)
        c.tracing.stop(path=str(dest / 'trace.zip'))
        for i, page in enumerate(c.pages):
            try:
                page.screenshot(path=str(dest / f'page-{i}.png'))
            except Exception:
                pass
    else:
        c.tracing.stop()
    c.close()


@pytest.fixture()
def page(ctx):
    return ctx.new_page()
