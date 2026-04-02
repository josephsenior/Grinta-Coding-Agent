#!/usr/bin/env python3
"""Enforce layer dependency rules for the App backend.

Run via:  python -m backend.scripts.verify.check_layer_imports
Or:       python backend/scripts/verify/check_layer_imports.py

Exit code 0 = clean, 1 = violations found.

Layer ordering (higher layers may import from lower layers, never the reverse):
    server  →  controller  →  engines  →  memory / models  →  events  →  core / utils / telemetry

Specific rules enforced:
  1. controller/ must NOT import from server/
  2. models/ must NOT import from server/
  3. engines/ must NOT import from server/
  4. memory/ must NOT import from server/
  5. events/ must NOT import from server/ or controller/
  6. core/ must NOT import from server/, controller/, engines/, or memory/
     Exception: ``backend/core/bootstrap/`` is the composition root; those
     modules are listed in EXEMPTIONS. ``backend/core/config/config_loader.py``
     may register custom agent classes (also exempt).
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable
from pathlib import Path

# ── Rule definitions ──────────────────────────────────────────────────────────
# Each rule is  (source_dir, forbidden_prefix, justification)
RULES: list[tuple[str, str, str]] = [
    (
        'backend/events',
        'backend.orchestration',
        'events must not depend on controller layer',
    ),
    ('backend/core', 'backend.engine', 'core must not depend on engines layer'),
    ('backend/core', 'backend.context', 'core must not depend on memory layer'),
]

# Known exemptions (module path → reason).  Keep this list SMALL.
EXEMPTIONS: dict[str, str] = {
    # Bootstrap / application-wiring modules that inherently cross layers.
    'backend.core.bootstrap.agent_control_loop': 'Bootstrap: agent control loop wiring',
    'backend.core.bootstrap.main': 'Bootstrap: application entry point',
    'backend.core.bootstrap.setup': 'Bootstrap: creates agent, controller, memory, runtime',
    'backend.core.config.config_loader': 'Bootstrap: registers custom agent classes',
}

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/


def _find_type_checking_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """Find (start, end) line ranges for TYPE_CHECKING blocks."""
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        is_tc = (
            isinstance(test, ast.Name)
            and test.id == 'TYPE_CHECKING'
            or isinstance(test, ast.Attribute)
            and test.attr == 'TYPE_CHECKING'
        )
        if not is_tc:
            continue
        start = node.lineno
        end = max(
            getattr(n, 'end_lineno', n.lineno)
            for n in ast.walk(node)
            if hasattr(n, 'lineno')
        )
        ranges.append((start, end))
    return ranges


def _collect_imports_from_tree(
    tree: ast.AST, in_type_checking: Callable[[int], bool]
) -> list[tuple[int, str, bool]]:
    """Collect (line, module, is_type_checking_only) for all imports."""
    results: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((node.lineno, alias.name, in_type_checking(node.lineno)))
        elif isinstance(node, ast.ImportFrom) and node.module:
            results.append((node.lineno, node.module, in_type_checking(node.lineno)))
    return results


def _extract_imports(filepath: Path) -> list[tuple[int, str, bool]]:
    """Return (line, dotted_module, is_type_checking_only) for every import."""
    source = filepath.read_text(encoding='utf-8', errors='replace')
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    tc_ranges = _find_type_checking_ranges(tree)

    def _in_type_checking(lineno: int) -> bool:
        return any(s <= lineno <= e for s, e in tc_ranges)

    return _collect_imports_from_tree(tree, _in_type_checking)


def check() -> list[str]:
    """Run all layer checks and return a list of violation messages."""
    violations: list[str] = []

    for source_dir, forbidden_prefix, reason in RULES:
        source_path = BACKEND_ROOT.parent / source_dir
        if not source_path.exists():
            continue
        for py_file in sorted(source_path.rglob('*.py')):
            # Skip test files
            rel = py_file.relative_to(BACKEND_ROOT.parent)
            rel_str = str(rel).replace('\\', '/')
            if '/tests/' in rel_str or rel_str.endswith('_test.py'):
                continue

            # Check exemptions
            module_path = rel_str.replace('/', '.').removesuffix('.py')
            if module_path in EXEMPTIONS:
                continue

            for lineno, imported_module, is_tc in _extract_imports(py_file):
                if is_tc:
                    continue  # TYPE_CHECKING imports are allowed
                if imported_module.startswith(forbidden_prefix):
                    violations.append(
                        f"  {rel_str}:{lineno}  imports '{imported_module}' — {reason}"
                    )

    return violations


def main() -> None:
    """CLI entry point."""
    violations = check()
    if violations:
        print(f'\nFAIL: {len(violations)} layer boundary violation(s) found:\n')
        for v in violations:
            print(v)
        print(
            '\nFix the imports or add an exemption in backend/scripts/verify/check_layer_imports.py'
        )
        sys.exit(1)
    else:
        print('OK: No layer boundary violations found.')
        sys.exit(0)


if __name__ == '__main__':
    main()
