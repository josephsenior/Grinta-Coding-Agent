"""Remove duplicate docstrings from split modules; keep __future__ first."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DOC = 'Split submodule — see package facade for public API.'

for pattern in (
    'backend/context/canonical_state_*.py',
    'backend/context/context_pipeline_*.py',
):
    for path in REPO.glob(pattern):
        text = path.read_text(encoding='utf-8')
        idx = text.find('from __future__ import annotations')
        if idx == -1:
            print('skip', path.name)
            continue
        path.write_text(f'"""{DOC}"""\n\n' + text[idx:], encoding='utf-8')
        print('fixed', path.name)
