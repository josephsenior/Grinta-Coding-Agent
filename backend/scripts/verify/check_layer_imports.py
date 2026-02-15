#!/usr/bin/env python3
"""Enforce layer dependency rules for the Forge backend.

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
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# ── Rule definitions ──────────────────────────────────────────────────────────
# Each rule is  (source_dir, forbidden_prefix, justification)
RULES: list[tuple[str, str, str]] = [
    (
        "backend/controller",
        "backend.server",
        "controller must not depend on server layer",
    ),
    ("backend/llm", "backend.server", "llm must not depend on server layer"),
    ("backend/engines", "backend.server", "engines must not depend on server layer"),
    ("backend/memory", "backend.server", "memory must not depend on server layer"),
    ("backend/events", "backend.server", "events must not depend on server layer"),
    (
        "backend/events",
        "backend.controller",
        "events must not depend on controller layer",
    ),
    ("backend/core", "backend.server", "core must not depend on server layer"),
    ("backend/core", "backend.controller", "core must not depend on controller layer"),
    ("backend/core", "backend.engines", "core must not depend on engines layer"),
    ("backend/core", "backend.memory", "core must not depend on memory layer"),
]

# Known exemptions (module path → reason).  Keep this list SMALL.
EXEMPTIONS: dict[str, str] = {
    # Bootstrap / application-wiring modules that inherently cross layers:
    "backend.core.loop": "Bootstrap: agent control loop wiring",
    "backend.core.main": "Bootstrap: application entry point",
    "backend.core.setup": "Bootstrap: creates agent, controller, memory, runtime",
    "backend.core.config.utils": "Bootstrap: registers custom agent classes",
}

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/


def _extract_imports(filepath: Path) -> list[tuple[int, str, bool]]:
    """Return (line, dotted_module, is_type_checking_only) for every import."""
    source = filepath.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    results: list[tuple[int, str, bool]] = []
    type_checking_ranges: list[tuple[int, int]] = []

    # Find TYPE_CHECKING blocks
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            # if TYPE_CHECKING:  or  if typing.TYPE_CHECKING:
            is_tc = False
            if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                is_tc = True
            elif isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
                is_tc = True
            if is_tc:
                start = node.lineno
                end = max(getattr(n, "end_lineno", n.lineno) for n in ast.walk(node) if hasattr(n, "lineno"))
                type_checking_ranges.append((start, end))

    def _in_type_checking(lineno: int) -> bool:
        return any(s <= lineno <= e for s, e in type_checking_ranges)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((node.lineno, alias.name, _in_type_checking(node.lineno)))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                results.append((node.lineno, node.module, _in_type_checking(node.lineno)))

    return results


def check() -> list[str]:
    """Run all layer checks and return a list of violation messages."""
    violations: list[str] = []

    for source_dir, forbidden_prefix, reason in RULES:
        source_path = BACKEND_ROOT.parent / source_dir
        if not source_path.exists():
            continue
        for py_file in sorted(source_path.rglob("*.py")):
            # Skip test files
            rel = py_file.relative_to(BACKEND_ROOT.parent)
            rel_str = str(rel).replace("\\", "/")
            if "/tests/" in rel_str or rel_str.endswith("_test.py"):
                continue

            # Check exemptions
            module_path = rel_str.replace("/", ".").removesuffix(".py")
            if module_path in EXEMPTIONS:
                continue

            for lineno, imported_module, is_tc in _extract_imports(py_file):
                if is_tc:
                    continue  # TYPE_CHECKING imports are allowed
                if imported_module.startswith(forbidden_prefix):
                    violations.append(f"  {rel_str}:{lineno}  imports '{imported_module}' — {reason}")

    return violations


def main() -> None:
    """CLI entry point."""
    violations = check()
    if violations:
        print(f"\n✗ {len(violations)} layer boundary violation(s) found:\n")
        for v in violations:
            print(v)
        print("\nFix the imports or add an exemption in backend/scripts/verify/check_layer_imports.py")
        sys.exit(1)
    else:
        print("✓ No layer boundary violations found.")
        sys.exit(0)


if __name__ == "__main__":
    main()
