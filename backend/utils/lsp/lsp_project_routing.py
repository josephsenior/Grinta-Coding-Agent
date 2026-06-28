"""Project-aware LSP server selection.

Two-stage resolution:

1. ``resolve_language_key`` — file extension + workspace markers → language
   key.  Marker-disambiguated ecosystems (Deno, Ansible, Helm) are detected
   via project-root files (``deno.json``, ``ansible.cfg``, ``Chart.yaml``).
2. ``lsp_context_for_file`` — language key → canonical server (exactly one
   per language) → resolved launch context.

No priority tuples, no fallback chains, no "first available wins".  Each
language has exactly one canonical server in ``CANONICAL_LSP_SERVERS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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

# Extensions shared between a default language and marker-based alternatives.
_DENO_EXTENSIONS = frozenset(
    {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.mts', '.cts'}
)
_YAML_EXTENSIONS = frozenset({'.yml', '.yaml'})


def find_project_root(start: Path) -> Path:
    """Walk upward from *start* to locate the nearest project root."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        if any((directory / marker).exists() for marker in _PROJECT_ROOT_MARKERS):
            return directory
    return current


def _has_deno_marker(root: Path) -> bool:
    return (root / 'deno.json').exists() or (root / 'deno.jsonc').exists()


def _has_ansible_marker(root: Path) -> bool:
    return (root / 'ansible.cfg').exists() or (root / 'requirements.yml').exists()


def _has_helm_marker(root: Path) -> bool:
    return (root / 'Chart.yaml').exists()


def resolve_language_key(ext: str, workspace_root: Path) -> str | None:
    """Return the language-resolution key for *ext* given project context.

    For marker-disambiguated extensions (.ts/.js, .yml/.yaml) the workspace
    root is inspected for ecosystem markers.  All other extensions map
    directly via the canonical extension table in ``runtime_detect``.
    """
    ext = ext.lower()
    if ext in _DENO_EXTENSIONS and _has_deno_marker(workspace_root):
        return 'deno'
    if ext in _YAML_EXTENSIONS:
        if _has_ansible_marker(workspace_root):
            return 'ansible'
        if _has_helm_marker(workspace_root):
            return 'helm'
    from backend.utils.runtime_detect import _EXTENSION_TO_LANGUAGE_KEY

    return _EXTENSION_TO_LANGUAGE_KEY.get(ext)


def lsp_context_for_file(
    file_path: str | Path,
    *,
    workspace_root: Path | None = None,
) -> LspFileContext | None:
    """Resolve server command, language id, and workspace root for *file_path*.

    Single source of truth for "which LSP runs for this file?":

    1. Find the project root (if not given).
    2. Resolve the language key from extension + markers.
    3. Look up the one canonical server for that language.
    4. Check it is installed; return the launch context or ``None``.
    """
    from backend.utils.runtime_detect import CANONICAL_LSP_SERVERS, detect_lsp_servers

    path = Path(file_path)
    ext = path.suffix.lower()
    if not ext:
        return None
    root = workspace_root if workspace_root is not None else find_project_root(path)
    language_key = resolve_language_key(ext, root)
    if language_key is None:
        return None
    spec = CANONICAL_LSP_SERVERS.get(language_key)
    if spec is None:
        return None
    tool = detect_lsp_servers().get(spec.name)
    if tool is None or not tool.available:
        return None
    return LspFileContext(
        server_name=spec.name,
        command=tool.resolved_command,
        language_id=spec.language,
        workspace_root=root,
    )
