"""The repo skill and the MCP server must name the same tools."""
import asyncio
import re
from pathlib import Path

from backend.mcp_server import mcp

SKILL = Path(__file__).resolve().parent.parent / "skills" / "typst-editor" / "SKILL.md"


def test_skill_names_exactly_the_registered_tools():
    tools = {t.name for t in asyncio.run(mcp.list_tools())}
    text = SKILL.read_text(encoding="utf-8")
    described = set(re.search(r"^description: .*\((.*?)\)", text, re.M).group(1).replace(" ", "").split(","))
    assert described == tools
    for name in tools:
        assert f"`{name}" in text, f"skill never mentions {name}"
