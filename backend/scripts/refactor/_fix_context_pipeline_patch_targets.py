"""Route context pipeline mixin runtime lookups through the facade for test patches."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / 'backend'

PATCHABLE_CALLS = (
    'finalize_compaction_artifacts',
    'delete_staging_snapshot',
    'maybe_update',
    'session_memory_exists',
    'build_compaction_summary',
    '_select_compaction_tail',
    '_projected_compaction_token_reduction',
)

MIXIN_FILES = [
    'context/context_pipeline/core_base.py',
    'context/context_pipeline/core_prepare.py',
    'context/context_pipeline/core_prompt.py',
    'context/context_pipeline/core_compact.py',
    'context/context_pipeline/core_state.py',
    'context/context_pipeline/core_gates.py',
]


def _ensure_cp_import(text: str) -> str:
    if 'import backend.context.context_pipeline as _cp' in text:
        return text
    return text.replace(
        'if TYPE_CHECKING:',
        'import backend.context.context_pipeline as _cp\n\nif TYPE_CHECKING:',
        1,
    )


def _fix_mixin(path: Path) -> None:
    text = path.read_text(encoding='utf-8')
    text = _ensure_cp_import(text)

    for name in PATCHABLE_CALLS:
        text = re.sub(rf'(?<![\w.]){re.escape(name)}\(', f'_cp.{name}(', text)

    text = re.sub(
        r'(?<![\w.])ContextBudget\.from_events\(',
        '_cp.ContextBudget.from_events(',
        text,
    )
    path.write_text(text, encoding='utf-8')
    print(f'patched {path.name}')


def _fix_helpers_shrink() -> None:
    path = ROOT / 'context' / 'context_pipeline' / 'helpers.py'
    text = path.read_text(encoding='utf-8')
    if '_cp._projected_compaction_token_reduction(' in text:
        return
    text = _ensure_cp_import(text)
    text = text.replace(
        'reduction = _projected_compaction_token_reduction(',
        'reduction = _cp._projected_compaction_token_reduction(',
    )
    path.write_text(text, encoding='utf-8')
    print('patched context_pipeline_helpers.py shrink lookup')


def main() -> None:
    for name in MIXIN_FILES:
        _fix_mixin(ROOT / name)
    _fix_helpers_shrink()


if __name__ == '__main__':
    main()
