"""Verify core modules do not import optional dependencies at top-level.

This is a lightweight static check meant to prevent optional extras from
breaking base installs. It scans for top-level `import X` / `from X import ...`
in core directories.
"""

from __future__ import annotations

import ast
import pathlib
import sys

OPTIONAL_TOP_LEVEL_MODULES = {
    # caching
    "redis",
    # memory
    "chromadb",
    "sentence_transformers",
    # telemetry
    "opentelemetry",
    "protobuf",
}


def _iter_py_files(root: pathlib.Path) -> list[pathlib.Path]:
    return [p for p in root.rglob("*.py") if p.is_file()]


def _top_module(name: str) -> str:
    return name.split(".", 1)[0]


def _check_file(path: pathlib.Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        return []

    violations: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _top_module(alias.name) in OPTIONAL_TOP_LEVEL_MODULES:
                    violations.append(f"{path}: top-level import '{alias.name}'")
        elif isinstance(node, ast.ImportFrom):
            if node.module and _top_module(node.module) in OPTIONAL_TOP_LEVEL_MODULES:
                violations.append(f"{path}: top-level from-import '{node.module}'")
    return violations


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    targets = [
        repo_root / "backend" / "core",
        repo_root / "backend" / "events",
        repo_root / "backend" / "server",
    ]

    all_violations: list[str] = []
    for target in targets:
        if not target.exists():
            continue
        for py in _iter_py_files(target):
            all_violations.extend(_check_file(py))

    if all_violations:
        sys.stderr.write("\n".join(all_violations) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
