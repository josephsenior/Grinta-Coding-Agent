"""Tests for project-aware LSP routing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from backend.utils.lsp.lsp_project_routing import (
    find_project_root,
    lsp_context_for_file,
    resolve_language_key,
)
from backend.utils.runtime_detect import CANONICAL_LSP_SERVERS, DetectedTool


def _tool(name: str, *, available: bool = True) -> DetectedTool:
    spec = next(s for s in CANONICAL_LSP_SERVERS.values() if s.name == name)
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


def test_python_resolves_to_canonical_pyright(tmp_path: Path) -> None:
    """Python has exactly one canonical server: pyright-langserver."""
    servers = {'pyright-langserver': _tool('pyright-langserver')}
    with patch('backend.utils.runtime_detect.detect_lsp_servers', return_value=servers):
        ctx = lsp_context_for_file(tmp_path / 'mod.py', workspace_root=tmp_path)
    assert ctx is not None
    assert ctx.server_name == 'pyright-langserver'
    assert ctx.language_id == 'python'


def test_python_no_fallback_when_pyright_missing(tmp_path: Path) -> None:
    """No fallback chain — if pyright is unavailable, python has no LSP."""
    servers = {'pyright-langserver': _tool('pyright-langserver', available=False)}
    with patch('backend.utils.runtime_detect.detect_lsp_servers', return_value=servers):
        ctx = lsp_context_for_file(tmp_path / 'mod.py', workspace_root=tmp_path)
    assert ctx is None


def test_deno_project_resolves_to_deno(tmp_path: Path) -> None:
    (tmp_path / 'deno.json').write_text('{}', encoding='utf-8')
    assert resolve_language_key('.ts', tmp_path) == 'deno'


def test_node_project_resolves_to_typescript(tmp_path: Path) -> None:
    (tmp_path / 'package.json').write_text(
        '{"devDependencies":{"typescript":"^5.0.0"}}',
        encoding='utf-8',
    )
    assert resolve_language_key('.ts', tmp_path) == 'typescript'


def test_javascript_extension_resolves_to_javascript(tmp_path: Path) -> None:
    assert resolve_language_key('.js', tmp_path) == 'javascript'


def test_yaml_resolves_to_ansible_with_marker(tmp_path: Path) -> None:
    (tmp_path / 'ansible.cfg').write_text('[defaults]\n', encoding='utf-8')
    assert resolve_language_key('.yml', tmp_path) == 'ansible'


def test_yaml_resolves_to_helm_with_chart_marker(tmp_path: Path) -> None:
    (tmp_path / 'Chart.yaml').write_text('apiVersion: v2\n', encoding='utf-8')
    assert resolve_language_key('.yaml', tmp_path) == 'helm'


def test_yaml_resolves_to_yaml_without_markers(tmp_path: Path) -> None:
    assert resolve_language_key('.yml', tmp_path) == 'yaml'


def test_lsp_context_for_file_uses_workspace(tmp_path: Path) -> None:
    (tmp_path / 'deno.json').write_text('{}', encoding='utf-8')
    src = tmp_path / 'main.ts'
    src.write_text('export {}', encoding='utf-8')
    servers = {
        'deno': _tool('deno'),
        'typescript-language-server': _tool('typescript-language-server'),
    }
    with patch('backend.utils.runtime_detect.detect_lsp_servers', return_value=servers):
        ctx = lsp_context_for_file(src)
    assert ctx is not None
    assert ctx.command == ('deno', 'lsp')
    assert ctx.language_id == 'typescript'
    assert ctx.workspace_root == tmp_path.resolve()
