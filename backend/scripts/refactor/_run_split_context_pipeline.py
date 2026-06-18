"""Split context_pipeline.py: extract module-level helpers."""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
path = REPO / 'backend/context/context_pipeline.py'
source = path.read_text(encoding='utf-8')
lines = source.splitlines(keepends=True)
header = ''.join(lines[:68]) + '\n'
doc = 'Split from ``context_pipeline.py``.'

types_body = ''.join(lines[68:101])
core_body = ''.join(lines[101:1143])
helpers_body = ''.join(lines[1150:])

parent = path.parent
(parent / 'context_pipeline_types.py').write_text(
    f'"""{doc}"""\n\n' + header + types_body, encoding='utf-8'
)
(parent / 'context_pipeline_core.py').write_text(
    f'"""{doc}"""\n\n' + header + core_body, encoding='utf-8'
)
(parent / 'context_pipeline_helpers.py').write_text(
    f'"""{doc}"""\n\n' + header + helpers_body, encoding='utf-8'
)

core_extra = '''
from backend.context.context_pipeline.helpers import (
    _drop_stale_prompt_state_artifacts,
    _latest_event_id,
    _pruned_ids,
    _projected_compaction_token_reduction,
    _select_compaction_tail,
    _shrink_tail_for_token_reduction,
    _synthetic_history_after_action,
    apply_ineffective_compaction_backoff,
)
from backend.context.context_pipeline.types import (
    PipelineStepResult,
    _ContinuityGateDecision,
)
'''
core_path = parent / 'context_pipeline_core.py'
core = core_path.read_text(encoding='utf-8').replace(
    'if TYPE_CHECKING:', core_extra + '\nif TYPE_CHECKING:', 1
)
core_path.write_text(core, encoding='utf-8')

helpers_extra = '''
from backend.context.prompt.context_packet import CONTEXT_PACKET_MARKER
from backend.ledger.event import Event
'''
helpers_path = parent / 'context_pipeline_helpers.py'
helpers = helpers_path.read_text(encoding='utf-8')
if 'CONTEXT_PACKET_MARKER' not in helpers.split('def _drop_stale')[0]:
    helpers = helpers.replace(
        'if TYPE_CHECKING:', helpers_extra + '\nif TYPE_CHECKING:', 1
    )
    helpers_path.write_text(helpers, encoding='utf-8')

def names_in(mod_path: Path) -> list[str]:
    mod = ast.parse(mod_path.read_text(encoding='utf-8'))
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
for suffix in ('types', 'core', 'helpers'):
    mod_path = parent / f'context_pipeline_{suffix}.py'
    mod_names = names_in(mod_path)
    all_names.extend(mod_names)
    blocks.append(
        f'from backend.context.context_pipeline_{suffix} import (\n    '
        + ',\n    '.join(mod_names)
        + ',\n)'
    )

facade = (
    '"""Unified context compaction pipeline — one ordered path for every LLM step."""\n\n'
    'from __future__ import annotations\n\n'
    + '\n'.join(blocks)
    + '\n\n__all__ = '
    + repr(sorted(set(all_names)))
    + '\n'
)
path.write_text(facade, encoding='utf-8')
print('core', len(core_body.splitlines()), 'helpers', len(helpers_body.splitlines()))
print('facade', len(set(all_names)), 'names')
