"""Dependencies mode for the analyze_project_structure tool.

This resurrects the capability that used to live in the (removed)
GraphRAG ``explore_tree_structure`` tool, but without a persistent
graph: every call does a bounded, cycle-safe BFS using the existing
AST + ripgrep + ignore plumbing. Results are useful for "what would
break if I touch this file?" (upstream) and "what files do I need to
read to understand this one?" (downstream).

Extracted from ``backend.engine.tools.analyze_project_structure`` to
keep that module focused on the public tool API.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

from backend.engine.tools._aps_shared import (
    _diag,
    _imports_reverse_via_rg,
    _imports_reverse_via_walk,
)
from backend.ledger.action import AgentThinkAction

_DEPENDENCY_MAX_DEPTH = 4
_DEPENDENCY_MAX_NODES = 200


def _module_to_candidate_paths(module: str, root: str) -> list[str]:
    """Map a dotted Python module to candidate workspace file paths.

    ``foo.bar.baz`` → ``[foo/bar/baz.py, foo/bar/baz/__init__.py]``. Returns
    only paths that actually exist; empty list when the module is external
    (stdlib, site-packages) or unresolvable in this workspace.
    """
    if not module or module.startswith('.'):
        return []
    parts = module.split('.')
    rel_module = os.path.join(*parts) + '.py'
    rel_pkg = os.path.join(*parts, '__init__.py')
    candidates: list[str] = []
    for rel in (rel_module, rel_pkg):
        full = os.path.join(root, rel)
        if os.path.isfile(full):
            candidates.append(rel.replace('\\', '/'))
    return candidates


def _downstream_imports(file_path: str, root: str) -> list[str]:
    """Return workspace-relative paths that ``file_path`` imports (best-effort).

    Only Python files are walked via AST. Non-Python files return an empty
    list; the dependency walk silently skips them.
    """
    abs_path = file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
    if not abs_path.endswith('.py') or not os.path.isfile(abs_path):
        return []
    try:
        src = Path(abs_path).read_text(encoding='utf-8', errors='ignore')
        tree = ast.parse(src)
    except (OSError, SyntaxError, ValueError):
        return []
    targets: list[str] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules = [node.module]
            modules.extend(f'{node.module}.{alias.name}' for alias in node.names)
        for module in modules:
            for cand in _module_to_candidate_paths(module, root):
                if cand not in targets:
                    targets.append(cand)
    return targets


def _upstream_importers(file_path: str, root: str) -> list[str]:
    """Return workspace-relative paths that import ``file_path`` (best-effort)."""
    basename = os.path.splitext(os.path.basename(file_path))[0]
    if not basename:
        return []
    rg_hits = _imports_reverse_via_rg(basename)
    raw = rg_hits if rg_hits is not None else _imports_reverse_via_walk(basename)
    cleaned: list[str] = []
    abs_target = os.path.abspath(
        file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
    )
    for hit in raw:
        norm = hit.lstrip('./').replace('\\', '/')
        if not norm:
            continue
        if os.path.abspath(os.path.join(root, norm)) == abs_target:
            continue
        if norm not in cleaned:
            cleaned.append(norm)
    return cleaned


def _walk_dependency_graph(
    start: str,
    *,
    direction: str,
    max_depth: int,
    root: str,
) -> tuple[dict[str, list[str]], set[str], bool]:
    """BFS over the import graph. Returns (edges, visited, truncated)."""
    edges: dict[str, list[str]] = {}
    visited: set[str] = {start}
    queue: list[tuple[str, int]] = [(start, 0)]
    truncated = False
    while queue:
        node, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        if direction == 'downstream':
            neighbors = _downstream_imports(node, root)
        elif direction == 'upstream':
            neighbors = _upstream_importers(node, root)
        else:
            neighbors = list(
                dict.fromkeys(
                    _downstream_imports(node, root) + _upstream_importers(node, root)
                )
            )
        edges[node] = neighbors
        for n in neighbors:
            if n in visited:
                continue
            if len(visited) >= _DEPENDENCY_MAX_NODES:
                truncated = True
                break
            visited.add(n)
            queue.append((n, depth + 1))
        if truncated:
            break
    return edges, visited, truncated


def _render_dependency_tree(
    start: str,
    edges: dict[str, list[str]],
    *,
    max_depth: int,
) -> list[str]:
    """ASCII tree rendering with cycle-aware ``(↺)`` markers."""
    lines: list[str] = []
    seen_on_path: set[str] = set()

    def _walk(node: str, depth: int, prefix: str) -> None:
        if depth > max_depth:
            return
        children = edges.get(node, [])
        for i, child in enumerate(children):
            is_last = i == len(children) - 1
            connector = '└── ' if is_last else '├── '
            cycle_marker = ' (↺)' if child in seen_on_path else ''
            lines.append(f'{prefix}{connector}{child}{cycle_marker}')
            if child in seen_on_path or child not in edges:
                continue
            seen_on_path.add(child)
            extension = '    ' if is_last else '│   '
            _walk(child, depth + 1, prefix + extension)
            seen_on_path.discard(child)

    lines.append(start)
    seen_on_path.add(start)
    _walk(start, 0, '')
    return lines


def _build_dependencies_action(
    path: str,
    *,
    depth: int,
    direction: str,
) -> AgentThinkAction:
    """Render an on-demand transitive import-graph for ``path``.

    Resurrects the removed GraphRAG ``explore_tree_structure`` capability
    without re-introducing a persistent index. The walk is bounded by both
    depth (capped at :data:`_DEPENDENCY_MAX_DEPTH`) and a hard node cap so
    a fan-out hub cannot explode the result.
    """
    direction = direction.lower().strip() or 'both'
    if direction not in ('upstream', 'downstream', 'both'):
        return AgentThinkAction(
            thought=_diag(
                reason=f'invalid direction {direction!r}',
                command='dependencies',
                params={'path': path, 'direction': direction, 'depth': depth},
                next_steps=["Use direction='upstream', 'downstream', or 'both'."],
            )
        )

    root = os.path.abspath('.')
    abs_path = path if os.path.isabs(path) else os.path.join(root, path)
    if not os.path.isfile(abs_path):
        return AgentThinkAction(
            thought=_diag(
                reason='anchor file not found',
                command='dependencies',
                params={'path': path, 'direction': direction, 'depth': depth},
                next_steps=[
                    'Pass a file path relative to the workspace root.',
                    'Run command=tree to discover the actual file location.',
                ],
            )
        )

    effective_depth = max(1, min(int(depth or 2), _DEPENDENCY_MAX_DEPTH))
    rel_start = os.path.relpath(abs_path, root).replace('\\', '/')

    edges, visited, truncated = _walk_dependency_graph(
        rel_start,
        direction=direction,
        max_depth=effective_depth,
        root=root,
    )

    out: list[str] = [
        '=== DEPENDENCY TREE ===',
        f'anchor: {rel_start}',
        f'direction: {direction}',
        f'depth: {effective_depth} (max={_DEPENDENCY_MAX_DEPTH})',
        f'nodes: {len(visited)} (cap={_DEPENDENCY_MAX_NODES}'
        f'{", TRUNCATED" if truncated else ""})',
        '',
    ]
    out.extend(_render_dependency_tree(rel_start, edges, max_depth=effective_depth))

    total_edges = sum(len(v) for v in edges.values())
    if total_edges == 0:
        out.append('')
        out.append(
            _diag(
                reason='no dependency edges found at this depth',
                command='dependencies',
                params={'path': path, 'direction': direction, 'depth': depth},
                next_steps=[
                    'Increase depth (capped at 4) for a wider view.',
                    "Try direction='both' to include upstream and downstream.",
                    'Verify the file actually contains/uses imports of in-workspace modules.',
                ],
            )
        )

    edge_payload = {
        'anchor': rel_start,
        'direction': direction,
        'depth': effective_depth,
        'truncated': truncated,
        'edges': {k: list(v) for k, v in edges.items()},
    }
    out.append('')
    out.append('=== EDGES (json) ===')
    out.append(json.dumps(edge_payload, indent=2, sort_keys=True))

    return AgentThinkAction(thought='\n'.join(out))
