"""Mechanically split a monolith .py file into sibling modules (pure code motion)."""

from __future__ import annotations

import argparse
import ast
import textwrap
from pathlib import Path


def _module_header(docstring: str | None, future: bool = True) -> str:
    lines: list[str] = []
    if future:
        lines.append('from __future__ import annotations')
        lines.append('')
    if docstring:
        lines.append(f'"""{docstring}"""')
        lines.append('')
    return '\n'.join(lines)


def _extract_slice(source: str, start: int, end: int) -> str:
    """Extract lines [start, end) (1-based inclusive start, exclusive end)."""
    lines = source.splitlines(keepends=True)
    return ''.join(lines[start - 1 : end - 1])


def _top_level_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def split_file(
    source_path: Path,
    slices: list[tuple[str, int, int, str | None]],
    *,
    facade_docstring: str | None = None,
) -> None:
    source = source_path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    module_doc = ast.get_docstring(tree)
    parent = source_path.parent
    stem = source_path.stem

    written: list[tuple[str, set[str]]] = []
    for suffix, start, end, doc in slices:
        target = parent / f'{stem}_{suffix}.py'
        body = _extract_slice(source, start, end).strip('\n') + '\n'
        header = _module_header(
            doc or f'Split from ``{source_path.name}``.', future=True
        )
        target.write_text(header + body, encoding='utf-8')
        names = _top_level_names(body)
        written.append((f'{stem}_{suffix}', names))
        print(f'wrote {target.name} ({end - start} lines, {len(names)} defs)')

    all_names: set[str] = set()
    for _, names in written:
        all_names |= names

    imports = '\n'.join(
        f'from {source_path.parent.name}.{mod} import *  # noqa: F403'
        for mod, _ in written
    )
    facade = textwrap.dedent(
        f"""\
        {module_doc or facade_docstring or f'Facade re-exporting ``{stem}_*`` submodules.'}

        {imports}

        __all__ = {sorted(all_names)!r}
        """
    )
    if not facade.startswith('"""'):
        facade = (
            f'"""{module_doc or facade_docstring or f"Facade for {stem}."}"""\n\n'
            + facade
        )
    source_path.write_text(
        'from __future__ import annotations\n\n' + facade, encoding='utf-8'
    )
    print(f'wrote facade {source_path.name}')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('slices', nargs='+', help='suffix:start:end[:doc]')
    args = parser.parse_args()
    source_path = Path(args.source)
    slices: list[tuple[str, int, int, str | None]] = []
    for spec in args.slices:
        parts = spec.split(':')
        suffix, start, end = parts[0], int(parts[1]), int(parts[2])
        doc = parts[3] if len(parts) > 3 else None
        slices.append((suffix, start, end, doc))
    split_file(source_path, slices)


if __name__ == '__main__':
    main()
