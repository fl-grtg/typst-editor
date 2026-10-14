"""The MCP resource listing and the files it can access must agree."""
import pytest
from conftest import register_user

from backend import mcp_tools as tools


@pytest.mark.anyio
async def test_mcp_can_create_read_and_edit_all_global_resource_kinds(c):
    register_user(c, 'mcp_resources')
    for name, original, replacement in [('references.bib', '@book{old,}', '@book{new,}'),
                                         ('numbers.csv', 'name,value\nAda,1', 'name,value\nAda,2')]:
        path = '/templates/' + name
        created = tools.op_create('mcp_resources', 'editor', path, original)
        assert created['name'] == name
        read = tools.op_read('mcp_resources', 'editor', path)
        assert read['content'] == original
        await tools.op_edit('mcp_resources', 'editor', path, original, replacement)
        assert tools.op_read('mcp_resources', 'editor', path)['content'] == replacement
    rows = c.get('/api/templates').json()['templates']
    assert {r['kind'] for r in rows} == {'library', 'table'}
    assert next(r for r in rows if r['name'].endswith('.bib'))['line'].startswith('#bibliography')


def test_mcp_file_list_includes_nested_project_files(c):
    from conftest import make_doc

    register_user(c, "mcp_nested")
    did = make_doc(c, title="Nested")
    assert c.post(f"/api/docs/{did}/files/chapters/nested.typ/text", json={"content": "Nested"}).status_code == 200
    rows = tools.op_ls("mcp_nested", "owner", "/docs/Nested")["files"]
    assert [row["name"] for row in rows] == ["chapters/nested.typ"]
