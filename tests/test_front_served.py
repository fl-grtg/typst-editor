from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_sw_shell_entries_served(c):
    # B21 guard: every served shell file must resolve (a precache addAll rejects on 404).
    from backend import main as backend_main

    for name in ("", *sorted(backend_main.FRONT_FILES)):
        url = "/" + name
        assert c.get(url).status_code == 200, f"shell entry not served: {url}"


def test_invite_link_prefill_static():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "checkInvite" in html
    assert "URLSearchParams(location.search)" in html
    assert "history.replaceState" in html  # token cleared from URL/history
    assert "$('inv').value" in html  # prefilled, never auto-submitted
    assert "/api/register" in html
