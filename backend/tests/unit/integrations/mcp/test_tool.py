from __future__ import annotations

from backend.integrations.mcp.tool import MCPClientTool


def test_to_param_includes_output_schema_hint() -> None:
    t = MCPClientTool(
        name='demo',
        description='desc',
        inputSchema={'type': 'object'},
        outputSchema={'type': 'array', 'items': {'type': 'string'}},
    )
    p = t.to_param()
    assert p['type'] == 'function'
    assert p['function']['name'] == 'demo'
    assert 'Output schema' in p['function']['description']


def test_to_param_includes_annotation_output_description() -> None:
    t = MCPClientTool(name='demo2', description='desc2', inputSchema={'type': 'object'})
    setattr(t, 'annotations', {'output_description': 'JSON rows'})
    p = t.to_param()
    assert 'Expected output: JSON rows' in p['function']['description']


def test_to_param_without_extra_metadata_keeps_description() -> None:
    t = MCPClientTool(name='demo3', description='base', inputSchema={'type': 'object'})
    p = t.to_param()
    assert p['function']['description'] == 'base'
