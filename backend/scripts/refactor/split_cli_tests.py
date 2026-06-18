"""Split monolithic CLI test files into backend/tests/unit/cli/{tui,frontend}/."""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _parse_module(path: Path) -> tuple[str, list[ast.stmt], list[str], str]:
    text = path.read_text(encoding='utf-8')
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    module_doc = ast.get_docstring(tree) or 'CLI tests'
    return text, tree.body, lines, module_doc  # type: ignore[return-value]


def _node_source(lines: list[str], node: ast.AST) -> str:
    start = getattr(node, 'lineno', 1) - 1
    if (
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.decorator_list
    ):
        start = (
            min(getattr(decorator, 'lineno', 1) for decorator in node.decorator_list)
            - 1
        )
    end = getattr(node, 'end_lineno', None) or getattr(node, 'lineno', 1)
    return ''.join(lines[start:end])


def _is_test(node: ast.stmt) -> bool:
    return isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef)
    ) and node.name.startswith('test_')


def _is_fixture(node: ast.stmt) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for dec in node.decorator_list:
        target = dec
        if isinstance(dec, ast.Call):
            target = dec.func
        if isinstance(target, ast.Attribute) and target.attr == 'fixture':
            return True
        if isinstance(target, ast.Name) and target.id == 'fixture':
            return True
    return False


def _frontend_bucket(name: str) -> str:
    if name.startswith('test_hud_'):
        return 'hud'
    if name.startswith('test_diff_'):
        return 'diff'
    if name.startswith('test_event_renderer_'):
        return 'event_renderer'
    if name.startswith('test_confirmation_'):
        return 'confirmation'
    if any(
        name.startswith(prefix)
        for prefix in (
            'test_command_completer_',
            'test_slash_command_',
            'test_prompt_',
            'test_unknown_command_',
            'test_help_',
            'test_autonomy_',
            'test_configure_redirected',
            'test_read_piped_stdin',
            'test_show_grinta_splash',
        )
    ):
        return 'repl'
    if any(
        token in name
        for token in ('thinking', 'reasoning', 'task_panel', 'task_list', 'sidebar')
    ):
        return 'rendering'
    if name.startswith('test_settings_'):
        return 'settings'
    return 'misc'


def _split_file(
    src: Path,
    dest_dir: Path,
    bucket_fn,
    *,
    module_doc: str,
) -> None:
    text, body, lines, doc = _parse_module(src)
    dest_dir.mkdir(parents=True, exist_ok=True)

    shared_parts: list[str] = []
    fixture_parts: list[str] = []
    buckets: dict[str, list[str]] = defaultdict(list)

    for node in body:
        if _is_test(node):
            buckets[bucket_fn(getattr(node, 'name', ''))].append(
                _node_source(lines, node)
            )
        elif _is_fixture(node):
            fixture_parts.append(_node_source(lines, node))
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            shared_parts.append(_node_source(lines, node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign)):
            shared_parts.append(_node_source(lines, node))

    shared_header = f'"""Shared imports and helpers for {module_doc}."""\n\n' + ''.join(
        shared_parts
    )
    (dest_dir / '_shared.py').write_text(shared_header, encoding='utf-8')

    conftest = (
        f'"""Pytest fixtures for {module_doc}."""\n\n'
        'from backend.tests.unit.cli.'
        f'{dest_dir.name}._shared import *  # noqa: F403\n\n' + ''.join(fixture_parts)
    )
    (dest_dir / 'conftest.py').write_text(conftest, encoding='utf-8')

    pkg = f'backend.tests.unit.cli.{dest_dir.name}'
    for bucket, parts in sorted(buckets.items()):
        content = (
            f'"""{module_doc} — {bucket}."""\n\n'
            f'from {pkg} import _shared\n'
            f'from {pkg}._shared import *  # noqa: F403\n'
            'for _name in dir(_shared):\n'
            '    if _name.startswith("_") and not _name.startswith("__"):\n'
            '        globals()[_name] = getattr(_shared, _name)\n\n' + '\n'.join(parts)
        )
        (dest_dir / f'test_{bucket}.py').write_text(content, encoding='utf-8')
        print(f'  {dest_dir.relative_to(REPO)}/test_{bucket}.py ({len(parts)} tests)')


def main() -> None:
    frontend_src = REPO / 'backend' / 'tests' / 'unit' / 'cli' / 'test_cli_frontend.py'

    print('Splitting test_cli_frontend.py')
    _split_file(
        frontend_src,
        REPO / 'backend' / 'tests' / 'unit' / 'cli' / 'frontend',
        _frontend_bucket,
        module_doc='CLI frontend',
    )


if __name__ == '__main__':
    main()
