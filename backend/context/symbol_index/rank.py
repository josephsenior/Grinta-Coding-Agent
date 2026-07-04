"""Graph ranking for repo-map file selection (Aider-style)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from backend.context.context_explorer import explore_context
from backend.context.symbol_index.store import SymbolIndexStore
from backend.engine.tools._aps_tree import _TREE_FILE_PRIORITY


def _pagerank(
    nodes: list[str],
    edges: list[tuple[str, str]],
    *,
    personalization: dict[str, float] | None = None,
    damping: float = 0.85,
    iterations: int = 24,
) -> dict[str, float]:
    if not nodes:
        return {}
    node_set = set(nodes)
    out_edges: dict[str, list[str]] = defaultdict(list)
    in_edges: dict[str, list[str]] = defaultdict(list)
    for src, dst in edges:
        if src in node_set and dst in node_set and src != dst:
            out_edges[src].append(dst)
            in_edges[dst].append(src)

    ranks = {node: 1.0 / len(nodes) for node in nodes}
    teleport = personalization or {}
    teleport_sum = sum(teleport.values()) or 1.0
    teleport_norm = {k: v / teleport_sum for k, v in teleport.items() if k in node_set}
    if not teleport_norm:
        teleport_norm = {node: 1.0 / len(nodes) for node in nodes}

    for _ in range(iterations):
        next_ranks: dict[str, float] = {}
        for node in nodes:
            incoming = 0.0
            for src in in_edges.get(node, []):
                outs = out_edges.get(src) or []
                if outs:
                    incoming += ranks[src] / len(outs)
            next_ranks[node] = (1.0 - damping) * teleport_norm.get(
                node, 0.0
            ) + damping * incoming
        total = sum(next_ranks.values()) or 1.0
        ranks = {node: score / total for node, score in next_ranks.items()}
    return ranks


def _entrypoint_boost(path: str) -> float:
    name = Path(path).name
    if name in _TREE_FILE_PRIORITY:
        return 1.0 - (_TREE_FILE_PRIORITY[name] * 0.05)
    return 0.0


def _task_boosts(task: str, workspace: Path) -> dict[str, float]:
    if not task.strip():
        return {}
    result = explore_context(task, workspace)
    boosts: dict[str, float] = {}
    for candidate in result.candidates:
        boosts[candidate.path] = max(
            boosts.get(candidate.path, 0.0), candidate.score / 100.0
        )
    for dirty in result.dirty_files:
        boosts[dirty] = max(boosts.get(dirty, 0.0), 0.35)
    return boosts


def rank_files_for_map(
    store: SymbolIndexStore,
    *,
    task: str,
    limit: int = 500,
) -> list[str]:
    """Return workspace-relative paths ordered by combined graph + task rank."""
    from backend.context.context_explorer import _repo_files

    repo_files = _repo_files(store.workspace_root)
    priority = sorted(
        repo_files,
        key=lambda path: (
            0 if Path(path).name in _TREE_FILE_PRIORITY else 1,
            path.count('/'),
            path.lower(),
        ),
    )
    store.warm_paths(priority, limit=limit)

    indexed = store.list_indexed_paths()
    if not indexed:
        return priority[: min(40, len(priority))]

    edges = store.list_import_edges()
    task_scores = _task_boosts(task, store.workspace_root)
    personalization = {
        path: 0.2 + task_scores.get(path, 0.0) + _entrypoint_boost(path)
        for path in indexed
    }
    graph_scores = _pagerank(indexed, edges, personalization=personalization)

    def combined(path: str) -> float:
        return (
            graph_scores.get(path, 0.0)
            + task_scores.get(path, 0.0)
            + _entrypoint_boost(path)
        )

    return sorted(indexed, key=lambda path: (-combined(path), path))
