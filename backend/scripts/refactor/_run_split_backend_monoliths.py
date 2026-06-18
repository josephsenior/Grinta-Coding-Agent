"""Split backend monolith modules into sibling submodules (pure code motion)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def split_module(
    rel_path: str,
    slices: dict[str, tuple[int, int]],
    cross_imports: dict[str, list[str]] | None = None,
) -> None:
    path = REPO / rel_path
    source = path.read_text(encoding='utf-8')
    lines = source.splitlines(keepends=True)
    parent = path.parent
    stem = path.stem

    # Find end of import block (first top-level def/class after imports)
    tree = ast.parse(source)
    import_end = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign)):
            import_end = max(import_end, node.end_lineno or 0)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            import_end = max(import_end, node.end_lineno or 0)
        else:
            break
    header = ''.join(lines[:import_end]) + '\n'

    all_names: list[str] = []
    import_blocks: list[str] = []
    for suffix, (start, end) in slices.items():
        target = parent / f'{stem}_{suffix}.py'
        body = ''.join(lines[start - 1 : end - 1])
        doc = ast.get_docstring(tree) or f'Split from ``{path.name}``.'
        content = f'"""{doc}"""\n\n' + header + body
        if cross_imports and suffix in cross_imports:
            extra = cross_imports[suffix]
            if extra:
                content = (
                    content.rstrip()
                    + '\n\n'
                    + '\n'.join(extra)
                    + '\n\n'
                    + body.lstrip('\n')
                )
                # rebuild properly
                content = f'"""{doc}"""\n\n' + header
                content += '\n'.join(extra) + '\n\n'
                content += body.lstrip('\n')
        target.write_text(content, encoding='utf-8')
        mod_names: list[str] = []
        mod = ast.parse(target.read_text(encoding='utf-8'))
        for node in mod.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                mod_names.append(node.name)
            elif isinstance(node, ast.Assign):
                for target_node in node.targets:
                    if isinstance(target_node, ast.Name):
                        mod_names.append(target_node.id)
        all_names.extend(mod_names)
        mod_stem = f'{stem}_{suffix}'
        import_blocks.append(
            f'from {path.parent.name}.{mod_stem} import (\n    '
            + ',\n    '.join(sorted(mod_names))
            + ',\n)'
        )
        print(f'  {target.name}: {end - start} lines, {len(mod_names)} names')

    module_doc = ast.get_docstring(tree) or f'Facade for {stem}.'
    facade = (
        f'"""{module_doc}"""\n\n'
        'from __future__ import annotations\n\n'
        + '\n'.join(import_blocks)
        + '\n\n__all__ = '
        + repr(sorted(set(all_names)))
        + '\n'
    )
    path.write_text(facade, encoding='utf-8')
    print(f'facade {path.name}: {len(set(all_names))} names')


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if target in ('all', 'llm'):
        print('=== llm.py ===')
        split_module(
            'backend/inference/llm.py',
            {
                'exceptions': (51, 253),
                'stream': (257, 323),
                'config': (325, 562),
                'core': (563, 9999),
            },
        )
    if target in ('all', 'canonical_state'):
        print('=== canonical_state.py ===')
        split_module(
            'backend/context/canonical_state.py',
            {
                'types': (22, 285),
                'io': (286, 321),
                'reduce': (322, 462),
                'render': (463, 584),
                'private': (585, 9999),
            },
            cross_imports={
                'io': [
                    'from backend.context.canonical_state.types import (',
                    '    CanonicalTaskState,',
                    '    SCHEMA_VERSION,',
                    '    _MAX_BLOCKERS,',
                    '    _MAX_DECISIONS,',
                    '    _known_dataclass_fields,',
                    ')',
                ],
                'reduce': [
                    'from backend.context.canonical_state_io import load_canonical_state, save_canonical_state',
                    'from backend.context.canonical_state.types import CanonicalTaskState',
                    'from backend.context.canonical_state.private import *  # noqa: F403',
                ],
                'render': [
                    'from backend.context.canonical_state.types import (',
                    '    CANONICAL_STATE_MARKER,',
                    '    CanonicalTaskState,',
                    '    CanonicalValidationResult,',
                    ')',
                    'from backend.context.canonical_state.private import *  # noqa: F403',
                ],
            },
        )
    if target in ('all', 'context_pipeline'):
        print('=== context_pipeline.py ===')
        split_module(
            'backend/context/context_pipeline.py',
            {
                'types': (69, 101),
                'core': (102, 1143),
                'helpers': (1151, 9999),
            },
            cross_imports={
                'core': [
                    'from backend.context.context_pipeline.types import (',
                    '    PipelineStepResult,',
                    '    _ContinuityGateDecision,',
                    ')',
                ],
                'helpers': [
                    'from backend.context.context_pipeline.types import PipelineStepResult',
                ],
            },
        )


if __name__ == '__main__':
    main()
