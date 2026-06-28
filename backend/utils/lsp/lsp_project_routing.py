"""Project-aware LSP server selection.

Uses workspace markers (``deno.json``, ``package.json``, ``pyproject.toml``, …)
to choose among *installed* language servers. Detection remains probe-only — no
downloads or silent installs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.utils.runtime_detect import DetectedTool, ToolSpec


@dataclass(frozen=True)
class LspFileContext:
    """Resolved language-server launch context for a file."""

    server_name: str
    command: tuple[str, ...]
    language_id: str
    workspace_root: Path

_PROJECT_ROOT_MARKERS = (
    'pyproject.toml',
    'package.json',
    'Cargo.toml',
    'go.mod',
    'deno.json',
    'deno.jsonc',
    'pom.xml',
    'build.gradle',
    'build.gradle.kts',
    '.git',
)

_JS_EXTENSIONS = frozenset(
    {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.mts', '.cts'}
)
_PY_EXTENSIONS = frozenset({'.py', '.pyw', '.pyi'})
_PRISMA_EXTENSIONS = frozenset({'.prisma'})
_NIX_EXTENSIONS = frozenset({'.nix'})
_OCAML_EXTENSIONS = frozenset({'.ml', '.mli'})
_TYPST_EXTENSIONS = frozenset({'.typ', '.typc'})


def find_project_root(start: Path) -> Path:
    """Walk upward from *start* to locate the nearest project root."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        if any((directory / marker).exists() for marker in _PROJECT_ROOT_MARKERS):
            return directory
    return current


def _has_deno_project(root: Path) -> bool:
    return (root / 'deno.json').exists() or (root / 'deno.jsonc').exists()


def _package_json_dep(root: Path, name: str) -> bool:
    pkg = root / 'package.json'
    if not pkg.is_file():
        return False
    try:
        data = json.loads(pkg.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return False
    for section in (
        'dependencies',
        'devDependencies',
        'peerDependencies',
        'optionalDependencies',
    ):
        deps = data.get(section)
        if isinstance(deps, dict) and name in deps:
            return True
    return False


def _prioritize(names: list[str], preferred: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in preferred:
        if name in names and name not in seen:
            ordered.append(name)
            seen.add(name)
    for name in names:
        if name not in seen:
            ordered.append(name)
            seen.add(name)
    return ordered


def preferred_lsp_server_names(
    ext: str,
    *,
    workspace_root: Path | None,
    registry_names: list[str],
) -> list[str]:
    """Return LSP server names in try-order for *ext* given project context."""
    ext = ext.lower()
    if ext in _PY_EXTENSIONS:
        return _prioritize(
            registry_names,
            [
                'pyright-langserver',
                'basedpyright-langserver',
                'pylsp',
                'ruff',
                'jedi-language-server',
            ],
        )

    if ext in _PRISMA_EXTENSIONS:
        return _prioritize(registry_names, ['prisma-language-server'])

    if ext in _NIX_EXTENSIONS:
        return _prioritize(registry_names, ['nixd', 'nil'])

    if ext in _OCAML_EXTENSIONS:
        return _prioritize(registry_names, ['ocamllsp'])

    if ext in _TYPST_EXTENSIONS:
        return _prioritize(registry_names, ['tinymist'])

    if ext in _JS_EXTENSIONS and workspace_root is not None:
        root = workspace_root
        if _has_deno_project(root):
            base = ['deno', 'typescript-language-server']
        elif _package_json_dep(root, 'typescript') or (root / 'tsconfig.json').is_file():
            base = ['typescript-language-server', 'deno']
        else:
            base = ['typescript-language-server', 'deno']
        lint_servers: list[str] = []
        if _package_json_dep(root, 'oxlint'):
            lint_servers.append('oxlint')
        if _package_json_dep(root, 'eslint'):
            lint_servers.append('eslint-language-server')
        if _package_json_dep(root, '@biomejs/biome') or _package_json_dep(root, 'biome'):
            lint_servers.append('biome')
        return _prioritize(registry_names, base + lint_servers)

    return list(registry_names)


def resolve_lsp_server_name(
    ext: str,
    servers: dict[str, DetectedTool],
    registry: tuple[ToolSpec, ...],
    *,
    workspace_root: Path | None = None,
) -> str | None:
    """Return the chosen installed server name for *ext*, or None."""
    ext = ext.lower()
    registry_names = [spec.name for spec in registry if ext in spec.extensions]
    order = preferred_lsp_server_names(
        ext,
        workspace_root=workspace_root,
        registry_names=registry_names,
    )
    for name in order:
        tool = servers.get(name)
        if tool and tool.available:
            return name
    return None


def lsp_context_for_file(file_path: str | Path) -> LspFileContext | None:
    """Resolve server command, language id, and workspace root for *file_path*."""
    from backend.utils.runtime_detect import LSP_SERVERS, detect_lsp_servers

    path = Path(file_path)
    ext = path.suffix.lower()
    if not ext:
        return None
    root = find_project_root(path)
    servers = detect_lsp_servers()
    name = resolve_lsp_server_name(
        ext, servers, LSP_SERVERS, workspace_root=root
    )
    if name is None:
        return None
    tool = servers[name]
    spec = next(s for s in LSP_SERVERS if s.name == name)
    return LspFileContext(
        server_name=name,
        command=tool.resolved_command,
        language_id=spec.language,
        workspace_root=root,
    )


def resolve_lsp_command(
    ext: str,
    servers: dict[str, DetectedTool],
    registry: tuple[ToolSpec, ...],
    *,
    workspace_root: Path | None = None,
) -> tuple[str, ...] | None:
    """Return the resolved command for the first matching installed server."""
    name = resolve_lsp_server_name(
        ext, servers, registry, workspace_root=workspace_root
    )
    if name is None:
        return None
    tool = servers[name]
    return tool.resolved_command
