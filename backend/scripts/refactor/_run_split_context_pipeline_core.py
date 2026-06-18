"""Split context_pipeline_core.py into mixin submodules."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
path = REPO / 'backend/context/context_pipeline_core.py'
source = path.read_text(encoding='utf-8')
lines = source.splitlines(keepends=True)
header = ''.join(lines[:94]) + '\n'
doc = 'Split from ``context_pipeline_core.py`` — mixin submodule.'

SLICES: dict[str, tuple[str, int, int]] = {
    'context_pipeline_core_base.py': (
        'ContextPipelineBaseMixin',
        97,
        236,
    ),
    'context_pipeline_core_prepare.py': (
        'ContextPipelinePrepareMixin',
        237,
        391,
    ),
    'context_pipeline_core_prompt.py': (
        'ContextPipelinePromptMixin',
        392,
        479,
    ),
    'context_pipeline_core_compact.py': (
        'ContextPipelineCompactionMixin',
        480,
        761,
    ),
    'context_pipeline_core_state.py': (
        'ContextPipelineStateMixin',
        762,
        841,
    ),
    'context_pipeline_core_gates.py': (
        'ContextPipelineGatesMixin',
        842,
        1118,
    ),
}

parent = path.parent
mixin_names: list[str] = []

for filename, (class_name, start, end) in SLICES.items():
    body = ''.join(lines[start - 1 : end - 1])
    # Drop leading "class ContextPipeline:" line if present in base slice
    if body.lstrip().startswith('class ContextPipeline:'):
        body_lines = body.splitlines(keepends=True)
        body = ''.join(body_lines[1:])
    content = (
        f'"""{doc}"""\n\n'
        + header
        + f'\nclass {class_name}:\n'
        + '    """ContextPipeline methods (mixin)."""\n\n'
        + body
    )
    target = parent / filename
    target.write_text(content, encoding='utf-8')
    mixin_names.append(class_name)
    print(filename, end - start, 'lines')

# _extract_pre_condensation_snapshot belongs on base mixin
base_path = parent / 'context_pipeline_core_base.py'
base = base_path.read_text(encoding='utf-8')
snapshot = ''.join(lines[1118:])
if '_extract_pre_condensation_snapshot' not in base:
    base = base.rstrip() + '\n\n' + snapshot
    base_path.write_text(base, encoding='utf-8')

facade = '''"""ContextPipeline class — composes mixin submodules."""

from __future__ import annotations

from backend.context.context_pipeline.core_base import (
    ContextPipelineBaseMixin,
    _EmptyState,
)
from backend.context.context_pipeline.core_compact import ContextPipelineCompactionMixin
from backend.context.context_pipeline.core_gates import ContextPipelineGatesMixin
from backend.context.context_pipeline.core_prepare import ContextPipelinePrepareMixin
from backend.context.context_pipeline.core_prompt import ContextPipelinePromptMixin
from backend.context.context_pipeline.core_state import ContextPipelineStateMixin


class ContextPipeline(
    ContextPipelinePrepareMixin,
    ContextPipelinePromptMixin,
    ContextPipelineCompactionMixin,
    ContextPipelineStateMixin,
    ContextPipelineGatesMixin,
    ContextPipelineBaseMixin,
):
    """Fixed-order context pipeline replacing compactor strategy roulette."""


__all__ = ['ContextPipeline', '_EmptyState']
'''
path.write_text(facade, encoding='utf-8')
print('facade', path.name)
