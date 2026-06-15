"""Regression tests for confirmation-state ownership."""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BACKEND_ROOT = _REPO_ROOT / 'backend'
_ALLOWED_AWAITING_ASSIGNERS = {
    Path('backend/orchestration/services/safety_service.py'),
}


def _contains_awaiting_confirmation(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Attribute)
            and child.attr == 'AWAITING_CONFIRMATION'
        ):
            return True
        if (
            isinstance(child, ast.Constant)
            and child.value == 'awaiting_confirmation'
        ):
            return True
    return False


def _sets_confirmation_state(target: ast.AST) -> bool:
    return isinstance(target, ast.Attribute) and target.attr == 'confirmation_state'


def _awaiting_confirmation_assignments(path: Path) -> list[tuple[Path, int]]:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    relative = path.relative_to(_REPO_ROOT)
    assignments: list[tuple[Path, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if not _contains_awaiting_confirmation(node.value):
                continue
            if any(_sets_confirmation_state(target) for target in node.targets):
                assignments.append((relative, node.lineno))
        elif isinstance(node, ast.AnnAssign):
            if node.value is None or not _contains_awaiting_confirmation(node.value):
                continue
            if _sets_confirmation_state(node.target):
                assignments.append((relative, node.lineno))
    return assignments


def test_only_safety_service_sets_awaiting_confirmation() -> None:
    offenders: list[tuple[Path, int]] = []
    allowed_hits: list[tuple[Path, int]] = []
    for path in _BACKEND_ROOT.rglob('*.py'):
        relative = path.relative_to(_REPO_ROOT)
        if 'tests' in relative.parts:
            continue
        for assignment in _awaiting_confirmation_assignments(path):
            if assignment[0] in _ALLOWED_AWAITING_ASSIGNERS:
                allowed_hits.append(assignment)
            else:
                offenders.append(assignment)

    assert offenders == []
    assert allowed_hits, 'SafetyService must remain the Layer 1 owner.'
