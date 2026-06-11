#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a static import manifest for the Grinta backend.

This is a read-only, AST-only analysis pass. It does NOT import the target
modules and does NOT execute project code. It walks ``backend/`` and
``launch/``, parses every ``.py`` file, and records:

* every ``import X`` and ``from X import Y`` statement
* the file and line number of each import
* the names brought into scope (``Y`` for ``from X import Y``)
* whether the import is inside a ``TYPE_CHECKING`` block (those are noted
  but treated as non-binding because they do not run at import time)

The output is a single JSON file describing the repository's module
graph. The primary use case is the file-size decomposition work tracked
in ``docs/ARCHITECTURE.md`` and ``docs/investigations/`` — before any
module is split, this manifest tells us exactly which files import the
target module and which names they reach for, so we can plan a
re-export shim that satisfies every consumer.

Run from the repository root::

    python scripts/discover_public_imports.py
    python scripts/discover_public_imports.py --output docs/internals/import-manifest.json
    python scripts/discover_public_imports.py --include-tests --quiet

Exit code is always 0 — the script is a measurement tool, not a gate.
For layer-boundary enforcement, see
``backend/scripts/verify/check_layer_imports.py``.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Repository layout ────────────────────────────────────────────────────────
# The script lives at <repo>/scripts/discover_public_imports.py. The
# backend root is <repo>/backend, and the launch package is <repo>/launch.
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / 'backend'
LAUNCH_ROOT = REPO_ROOT / 'launch'

# Directories that are not part of the production graph we care about.
SKIP_PATH_SUBSTRINGS: tuple[str, ...] = (
    os.sep + '__pycache__' + os.sep,
    os.sep + '.mypy_cache' + os.sep,
    os.sep + '.ruff_cache' + os.sep,
    os.sep + '.pytest_cache' + os.sep,
)

# Tests import a lot of internal stuff. By default we exclude them from
# the manifest because they are *consumers* of the public surface, not
# providers of it. Pass --include-tests to include them.
DEFAULT_EXCLUDED_TOP_DIRS: tuple[str, ...] = ('tests',)

# Modules known to be candidate decomposition targets. The summary
# section always surfaces the top-N largest files; this list adds the
# specific monoliths we plan to split so they show up even if other
# files overtake them in size during the decomp work.
KNOWN_MONOLITHS: tuple[str, ...] = (
    'backend.cli.tui.app',
    'backend.engine.function_calling',
    'backend.engine.executor',
    'backend.orchestration.session_orchestrator',
    'backend.orchestration.services.event_router_service',
    'backend.cli.event_renderer',
    'backend.cli.repl',
    'backend.inference.direct_clients',
    'backend.inference.fn_call',
    'backend.execution.debugger',
    'backend.cli.theme',
)

# ── Data model ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImportRecord:
    """One concrete import statement observed in the source."""

    importer: str  # e.g. "backend/cli/tui/main.py"
    lineno: int
    module: str  # dotted module path, e.g. "backend.cli.tui.app"
    names: tuple[str, ...]  # names imported; empty for `import X`
    is_type_checking: bool  # True if inside `if TYPE_CHECKING:`


@dataclass
class ModuleInfo:
    """Aggregated facts about one module on disk."""

    module_path: str  # e.g. "backend.cli.tui.app"
    file_path: str  # repo-relative POSIX path
    byte_size: int
    loc: int  # physical lines (readlines())
    class_count: int
    def_count: int  # top-level def + async def
    imported_by: list[dict[str, Any]] = field(default_factory=list)
    intra_package_imports: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'module_path': self.module_path,
            'file_path': self.file_path,
            'byte_size': self.byte_size,
            'loc': self.loc,
            'class_count': self.class_count,
            'def_count': self.def_count,
            'importer_count': len(self.imported_by),
            'intra_package_imports': self.intra_package_imports,
            'imported_by': self.imported_by,
        }


# ── AST helpers ──────────────────────────────────────────────────────────────


def _find_type_checking_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    """Find (start_line, end_line) for every `if TYPE_CHECKING:` block."""
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        is_tc = (isinstance(test, ast.Name) and test.id == 'TYPE_CHECKING') or (
            isinstance(test, ast.Attribute) and test.attr == 'TYPE_CHECKING'
        )
        if not is_tc:
            continue
        start = node.lineno
        # end_lineno is 3.8+; fall back to the start line if missing.
        end_candidates = [
            getattr(n, 'end_lineno', n.lineno)
            for n in ast.walk(node)
            if hasattr(n, 'lineno')
        ]
        end = max(end_candidates) if end_candidates else start
        ranges.append((start, end))
    return ranges


def _extract_imports(
    filepath: Path,
) -> list[ImportRecord]:
    """Return every import statement in ``filepath`` with its location."""
    try:
        source = filepath.read_text(encoding='utf-8', errors='replace')
        tree = ast.parse(source, filename=str(filepath))
    except (OSError, SyntaxError):
        # Unreadable or syntactically broken files contribute nothing
        # to the manifest. They will be picked up by ruff/mypy/pytest.
        return []

    tc_ranges = _find_type_checking_ranges(tree)

    def _in_type_checking(lineno: int) -> bool:
        return any(s <= lineno <= e for s, e in tc_ranges)

    records: list[ImportRecord] = []
    rel = filepath.relative_to(REPO_ROOT).as_posix()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                records.append(
                    ImportRecord(
                        importer=rel,
                        lineno=node.lineno,
                        module=alias.name,
                        names=(),
                        is_type_checking=_in_type_checking(node.lineno),
                    )
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = tuple(alias.name for alias in node.names)
            records.append(
                ImportRecord(
                    importer=rel,
                    lineno=node.lineno,
                    module=node.module,
                    names=names,
                    is_type_checking=_in_type_checking(node.lineno),
                )
            )
    return records


def _count_top_level_defs(tree: ast.Module) -> tuple[int, int]:
    """Return (class_count, def_count) for top-level definitions in ``tree``."""
    classes = 0
    defs = 0
    for node in tree.body:  # body only — not nested defs
        if isinstance(node, ast.ClassDef):
            classes += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs += 1
    return classes, defs


def _iter_python_files(roots: Iterable[Path]) -> Iterable[Path]:
    """Yield production ``.py`` files under each root, honouring skips."""
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob('*.py')):
            posix = path.as_posix()
            if any(skip in posix for skip in SKIP_PATH_SUBSTRINGS):
                continue
            if not _include_tests:
                rel_parts = path.relative_to(REPO_ROOT).parts
                if any(part in DEFAULT_EXCLUDED_TOP_DIRS for part in rel_parts):
                    continue
            yield path


# ── Manifest assembly ────────────────────────────────────────────────────────


def _module_path_for(filepath: Path) -> str:
    """Convert a ``.py`` file path to its dotted module path."""
    rel = filepath.relative_to(REPO_ROOT).with_suffix('')
    return rel.as_posix().replace('/', '.')


def _classify(module: str) -> str:
    """Bucket a module reference for the summary statistics."""
    if module.startswith('backend.') or module == 'backend':
        return 'internal'
    if module.startswith('launch.'):
        return 'internal'
    if (
        module in sys.stdlib_module_names
        or module.split('.', 1)[0] in sys.stdlib_module_names
    ):
        return 'stdlib'
    return 'third_party'


def _parse_python_file(
    path: Path, rel: str
) -> tuple[ModuleInfo | None, list[ImportRecord], str | None]:
    try:
        byte_size = path.stat().st_size
        loc = sum(1 for _ in path.open('rb'))
    except OSError:
        return None, [], rel

    parse_failure: str | None = None
    try:
        tree = ast.parse(
            path.read_text(encoding='utf-8', errors='replace'),
            filename=str(path),
        )
        class_count, def_count = _count_top_level_defs(tree)
    except SyntaxError:
        class_count = 0
        def_count = 0
        parse_failure = rel

    module_path = _module_path_for(path)
    info = ModuleInfo(
        module_path=module_path,
        file_path=rel,
        byte_size=byte_size,
        loc=loc,
        class_count=class_count,
        def_count=def_count,
    )
    imports = _extract_imports(path)
    return info, imports, parse_failure


def _compute_package_edges(
    all_imports: list[ImportRecord], modules: dict[str, ModuleInfo]
) -> None:
    package_edges: dict[str, set[str]] = {}
    for record in all_imports:
        if not (
            record.module.startswith('backend.') or record.module.startswith('launch.')
        ):
            continue
        if record.is_type_checking:
            continue
        importer_pkg = record.importer.split('/', 1)[0]
        target_pkg = record.module.split('.', 1)[0]
        if importer_pkg != target_pkg:
            continue
        importer_mod = record.importer.removesuffix('.py').replace('/', '.')
        package_edges.setdefault(importer_mod, set()).add(record.module)

    for module_path, info in modules.items():
        info.intra_package_imports = sorted(
            pkg for pkg in package_edges.get(module_path, set()) if pkg != module_path
        )


def _compute_public_surface(
    modules: dict[str, ModuleInfo],
) -> dict[str, list[dict[str, Any]]]:
    public_surface: dict[str, list[dict[str, Any]]] = {}
    for monolith in KNOWN_MONOLITHS:
        if monolith not in modules:
            continue
        names: Counter[str] = Counter()
        for entry in modules[monolith].imported_by:
            if entry['is_type_checking']:
                continue
            for name in entry['names']:
                names[name] += 1
        public_surface[monolith] = [
            {'name': name, 'import_count': count} for name, count in names.most_common()
        ]
    return public_surface


def _build_manifest_summary(
    modules: dict[str, ModuleInfo],
    all_imports: list[ImportRecord],
    parse_failures: list[str],
) -> dict[str, Any]:
    classification = Counter(_classify(r.module) for r in all_imports)
    type_checking_only = sum(1 for r in all_imports if r.is_type_checking)
    return {
        'module_count': len(modules),
        'import_count': len(all_imports),
        'type_checking_only_import_count': type_checking_only,
        'parse_failure_count': len(parse_failures),
        'import_classification': dict(classification),
    }


def _build_manifest_sorteds(
    modules: dict[str, ModuleInfo],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    most_imported = sorted(
        modules.values(),
        key=lambda m: (-len(m.imported_by), m.byte_size),
    )[:25]
    biggest_files = sorted(
        modules.values(),
        key=lambda m: -m.byte_size,
    )[:25]
    most_imported_dicts = [
        {
            'module_path': m.module_path,
            'file_path': m.file_path,
            'byte_size': m.byte_size,
            'importer_count': len(m.imported_by),
        }
        for m in most_imported
    ]
    biggest_files_dicts = [
        {
            'module_path': m.module_path,
            'file_path': m.file_path,
            'byte_size': m.byte_size,
            'loc': m.loc,
            'importer_count': len(m.imported_by),
        }
        for m in biggest_files
    ]
    return most_imported_dicts, biggest_files_dicts


def build_manifest(roots: Iterable[Path]) -> dict[str, Any]:
    """Walk ``roots`` and return the full manifest dict."""
    files = list(_iter_python_files(roots))
    modules: dict[str, ModuleInfo] = {}
    all_imports: list[ImportRecord] = []
    parse_failures: list[str] = []

    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        info, imports, failure = _parse_python_file(path, rel)
        if info is None:
            parse_failures.append(failure)
            continue
        if failure is not None:
            parse_failures.append(failure)
        modules[info.module_path] = info
        for record in imports:
            all_imports.append(record)
            target = record.module
            if target in modules:
                modules[target].imported_by.append(
                    {
                        'importer': record.importer,
                        'lineno': record.lineno,
                        'names': list(record.names),
                        'is_type_checking': record.is_type_checking,
                    }
                )

    _compute_package_edges(all_imports, modules)
    public_surface = _compute_public_surface(modules)
    summary = _build_manifest_summary(modules, all_imports, parse_failures)
    most_imported, biggest_files = _build_manifest_sorteds(modules)

    return {
        'schema_version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'repository_root': REPO_ROOT.as_posix(),
        'options': {
            'include_tests': _include_tests,
        },
        'summary': summary,
        'biggest_files': biggest_files,
        'most_imported': most_imported,
        'public_surface': public_surface,
        'modules': {path: info.to_dict() for path, info in sorted(modules.items())},
        'parse_failures': parse_failures,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────


def _print_summary(manifest: dict[str, Any]) -> None:
    # Reconfigure stdout for the summary so the caller can see non-ASCII
    # glyphs (arrows, bullets) even on Windows consoles that default to
    # cp1252. We do this lazily and only for the summary, not for the
    # manifest writer, which always writes UTF-8 JSON.
    stdout = sys.stdout
    reconfigure = getattr(stdout, 'reconfigure', None)
    if reconfigure is not None:
        try:
            reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass

    summary = manifest['summary']
    print(
        f'Discovered {summary["module_count"]} modules, '
        f'{summary["import_count"]} imports '
        f'({summary["type_checking_only_import_count"]} inside TYPE_CHECKING).'
    )
    cls = summary['import_classification']
    print(
        f'  internal={cls.get("internal", 0)}  '
        f'stdlib={cls.get("stdlib", 0)}  '
        f'third_party={cls.get("third_party", 0)}'
    )
    if summary['parse_failure_count']:
        print(
            f'  parse failures: {summary["parse_failure_count"]} '
            f"(see manifest['parse_failures'])"
        )
    print()
    print('Top 10 biggest files:')
    for entry in manifest['biggest_files'][:10]:
        kb = entry['byte_size'] / 1024.0
        print(
            f'  {kb:7.1f} KB  {entry["module_path"]:60s}  '
            f'({entry["importer_count"]} importers)'
        )
    print()
    print('Top 10 most-imported modules:')
    for entry in manifest['most_imported'][:10]:
        print(
            f'  {entry["importer_count"]:4d} importers  '
            f'{entry["module_path"]:60s}  '
            f'({entry["byte_size"] / 1024.0:6.1f} KB)'
        )
    print()
    if manifest['public_surface']:
        print('Public surface of known monoliths (name -> # importers):')
        for monolith, names in manifest['public_surface'].items():
            if not names:
                print(f'  {monolith}: (no external importers)')
                continue
            top = ', '.join(f'{n["name"]}×{n["import_count"]}' for n in names[:6])
            extra = f'  (+{len(names) - 6} more)' if len(names) > 6 else ''
            print(f'  {monolith}: {top}{extra}')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else 'discover imports',
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=REPO_ROOT / 'docs' / 'internals' / 'import-manifest.json',
        help='Path to write the JSON manifest (default: docs/internals/import-manifest.json).',
    )
    parser.add_argument(
        '--include-tests',
        action='store_true',
        help='Include backend/tests/ and other test directories in the walk.',
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Skip the human-readable summary printed to stdout.',
    )
    args = parser.parse_args(argv)

    global _include_tests
    _include_tests = args.include_tests

    roots = [BACKEND_ROOT, LAUNCH_ROOT]
    manifest = build_manifest(roots)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + '\n',
        encoding='utf-8',
    )

    if not args.quiet:
        print(f'Manifest written to {args.output.relative_to(REPO_ROOT).as_posix()}')
        print()
        _print_summary(manifest)
    return 0


# Module-level state for the test/include-tests toggle. Defaults to False
# (production graph only) and is flipped by the CLI in main().
_include_tests = False


if __name__ == '__main__':
    sys.exit(main())
