"""Tests for project-aware LSP routing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from backend.utils.lsp.lsp_project_routing import (
    find_project_root,
    preferred_lsp_server_names,
    resolve_lsp_command,
)
from backend.utils.runtime_detect import DetectedTool, LSP_SERVERS


def _tool(name: str, *, available: bool = True) -> DetectedTool:
    spec = next(s for s in LSP_SERVERS if s.name == name)
    return DetectedTool(
        spec=spec,
        available=available,
        resolved_command=spec.command,
        detail='ok',
    )


def test_find_project_root_from_nested_file(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="x"\n', encoding='utf-8')
    nested = tmp_path / 'src' / 'pkg'
    nested.mkdir(parents=True)
    assert find_project_root(nested / 'mod.py') == tmp_path.resolve()


def test_python_prefers_pyright_when_both_installed(tmp_path: Path) -> None:
    servers = {
        'pyright-langserver': _tool('pyright-langserver'),
        'pylsp': _tool('pylsp'),
    }
    cmd = resolve_lsp_command(
        '.py',
        servers,
        LSP_SERVERS,
        workspace_root=tmp_path,
    )
    assert cmd == LSP_SERVERS[0].command


def test_python_falls_back_to_pylsp(tmp_path: Path) -> None:
    servers = {
        'pyright-langserver': _tool('pyright-langserver', available=False),
        'pylsp': _tool('pylsp'),
    }
    cmd = resolve_lsp_command(
        '.py',
        servers,
        LSP_SERVERS,
        workspace_root=tmp_path,
    )
    assert cmd is not None and cmd[-1] == 'pylsp'


def test_deno_project_prefers_deno_for_typescript(tmp_path: Path) -> None:
    (tmp_path / 'deno.json').write_text('{}', encoding='utf-8')
    names = preferred_lsp_server_names(
        '.ts',
        workspace_root=tmp_path,
        registry_names=['typescript-language-server', 'deno'],
    )
    assert names[0] == 'deno'


def test_node_project_prefers_typescript_language_server(tmp_path: Path) -> None:
    (tmp_path / 'package.json').write_text(
        '{"devDependencies":{"typescript":"^5.0.0"}}',
        encoding='utf-8',
    )
    names = preferred_lsp_server_names(
        '.ts',
        workspace_root=tmp_path,
        registry_names=['typescript-language-server', 'deno'],
    )
    assert names[0] == 'typescript-language-server'


def test_lsp_context_for_file_uses_workspace(tmp_path: Path) -> None:
    (tmp_path / 'deno.json').write_text('{}', encoding='utf-8')
    src = tmp_path / 'main.ts'
    src.write_text('export {}', encoding='utf-8')
    servers = {
        'deno': _tool('deno'),
        'typescript-language-server': _tool('typescript-language-server'),
    }
    with patch('backend.utils.runtime_detect.detect_lsp_servers', return_value=servers):
        from backend.utils.lsp.lsp_project_routing import lsp_context_for_file

        ctx = lsp_context_for_file(src)
    assert ctx is not None
    assert ctx.command == ('deno', 'lsp')
    assert ctx.language_id == 'typescript'
    assert ctx.workspace_root == tmp_path.resolve()
