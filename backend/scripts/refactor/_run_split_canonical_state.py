"""Split canonical_state.py into types, ops, and private helpers."""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
path = REPO / 'backend/context/canonical_state.py'
source = path.read_text(encoding='utf-8')
lines = source.splitlines(keepends=True)
header = ''.join(lines[:21]) + '\n'
doc = 'Split from ``canonical_state.py`` — see facade for public API.'

types_body = ''.join(lines[21:284]) + ''.join(lines[615:621])
ops_body = ''.join(lines[285:614])
private_body = ''.join(lines[621:])

parent = path.parent
(parent / 'canonical_state_types.py').write_text(
    f'"""{doc}"""\n\n' + header + types_body, encoding='utf-8'
)
(parent / 'canonical_state_ops.py').write_text(
    f'"""{doc}"""\n\n' + header + ops_body, encoding='utf-8'
)
(parent / 'canonical_state_private.py').write_text(
    f'"""{doc}"""\n\n' + header + private_body, encoding='utf-8'
)

ops_extra = '''
from backend.context.canonical_state.private import (
    _can_update,
    _clean,
    _coerce_string_list,
    _extract_next_action,
    _import_legacy_state,
    _infer_next_action,
    _is_pivot_directive,
    _latest_event_id,
    _merge_background_tasks,
    _merge_failed_approaches,
    _merge_recent_work,
    _merge_strings,
    _merge_task_plan,
    _now,
    _resolve_background_tasks_from_events,
    _set_field,
    _snapshot_latest_event_id,
    _string_tail,
    _touch_field,
    _update_blockers,
    _update_vcs_status,
    _update_verification,
)
from backend.context.canonical_state.types import (
    CANONICAL_STATE_MARKER,
    CanonicalTaskState,
    CanonicalValidationResult,
)
'''
ops_path = parent / 'canonical_state_ops.py'
ops = ops_path.read_text(encoding='utf-8').replace(
    'if TYPE_CHECKING:', ops_extra + '\nif TYPE_CHECKING:', 1
)
ops_path.write_text(ops, encoding='utf-8')

priv_extra = '''
from backend.context.canonical_state.types import (
    BackgroundTaskState,
    CanonicalTaskState,
    FailedApproach,
    FieldFreshness,
    RecentWorkItem,
    TaskPlanItem,
    VerificationState,
    clip_with_marker,
)
'''
priv_path = parent / 'canonical_state_private.py'
priv = priv_path.read_text(encoding='utf-8').replace(
    'if TYPE_CHECKING:', priv_extra + '\nif TYPE_CHECKING:', 1
)
priv_path.write_text(priv, encoding='utf-8')

def names_in(path: Path) -> list[str]:
    mod = ast.parse(path.read_text(encoding='utf-8'))
    out: list[str] = []
    for node in mod.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.append(t.id)
    return sorted(set(out))

all_names: list[str] = []
blocks: list[str] = []
for suffix in ('types', 'ops', 'private'):
    mod_path = parent / f'canonical_state_{suffix}.py'
    mod_names = names_in(mod_path)
    all_names.extend(mod_names)
    blocks.append(
        f'from backend.context.canonical_state_{suffix} import (\n    '
        + ',\n    '.join(mod_names)
        + ',\n)'
    )

facade = (
    '"""Canonical task state for long-running coding-agent continuity."""\n\n'
    'from __future__ import annotations\n\n'
    + '\n'.join(blocks)
    + '\n\n__all__ = '
    + repr(sorted(set(all_names)))
    + '\n'
)
path.write_text(facade, encoding='utf-8')
print('types', len(types_body.splitlines()), 'ops', len(ops_body.splitlines()), 'private', len(private_body.splitlines()))
print('facade', len(set(all_names)), 'names')
