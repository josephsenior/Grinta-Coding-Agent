"""Split unified_renderer.py into backend/cli/event_rendering/unified_renderer/."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'cli' / 'event_rendering' / 'unified_renderer.py'
TARGET = ROOT / 'cli' / 'event_rendering' / 'unified_renderer'

MIXIN_RANGES: dict[str, tuple[int, int]] = {
    'shell': (216, 421),
    'file': (423, 514),
    'mcp': (516, 796),
    'browser': (798, 861),
    'code': (863, 894),
    'delegate': (896, 938),
    'terminal': (940, 1029),
    'status': (1031, 1091),
    'exploration': (1093, 1416),
}

MIXIN_IMPORTS: dict[str, str] = {
    'shell': """from __future__ import annotations

import re

from backend.cli.event_rendering.unified_renderer.types import ActivityCard, ActivityLine
from backend.cli.event_rendering.unified_renderer.utils import (
    _SEARCH_CARD_PRESETS,
    _extract_search_query,
    _looks_error_heavy,
)
from backend.cli.theme import NAVY_TEXT_DIM, NAVY_TEXT_MUTED
""",
    'file': """from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import ActivityCard, ActivityLine
from backend.cli.event_rendering.unified_renderer.utils import (
    _lexer_for_path,
    _looks_error_heavy,
)
from backend.cli.theme import NAVY_TEXT_DIM, NAVY_WAITING
""",
    'mcp': """from __future__ import annotations

import json
from typing import Any

from backend.cli.event_rendering.unified_renderer.types import ActivityCard, ActivityLine
from backend.cli.event_rendering.unified_renderer.utils import (
    _WEB_CARD_PRESETS,
    _WEB_MCP_KINDS,
    _exploration_meta_line,
)
from backend.cli.tool_display.preview import mcp_result_user_preview
from backend.cli.theme import NAVY_TEXT_DIM, NAVY_TEXT_MUTED
""",
    'browser': """from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import ActivityCard, ActivityLine
from backend.cli.event_rendering.unified_renderer.utils import (
    _BROWSER_OUTCOMES,
    _exploration_meta_line,
)
from backend.cli.theme import NAVY_ERROR, NAVY_TEXT_DIM
""",
    'code': """from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import ActivityCard, ActivityLine
from backend.cli.theme import NAVY_TEXT_MUTED
""",
    'delegate': """from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import ActivityCard, ActivityLine
from backend.cli.event_rendering.unified_renderer.utils import _looks_error_heavy
from backend.cli.theme import NAVY_TEXT_DIM, NAVY_TEXT_MUTED
""",
    'terminal': """from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import ActivityCard, ActivityLine
from backend.cli.event_rendering.unified_renderer.utils import (
    _looks_error_heavy,
    _strip_ansi,
)
from backend.cli.theme import NAVY_TEXT_DIM, NAVY_TEXT_MUTED
""",
    'status': """from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import ActivityCard, ActivityLine
""",
    'exploration': """from __future__ import annotations

from backend.cli.event_rendering.unified_renderer.types import ActivityCard, ActivityLine
from backend.cli.event_rendering.unified_renderer.utils import _SEARCH_CARD_PRESETS
from backend.cli.theme import NAVY_TEXT_DIM, NAVY_TEXT_MUTED
""",
}

UTILS_HEADER = '''"""Shared helpers and presets for unified activity rendering."""

from __future__ import annotations

import re

from pygments.lexers import guess_lexer_for_filename
from pygments.util import ClassNotFound
from rich.text import Text

'''

TYPES_HEADER = '''"""Activity card data structures."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.cli.tool_display.renderers.badge import badge_for_tool_name
from backend.cli.theme import (
    NAVY_BRAND,
    NAVY_ERROR,
    NAVY_READY,
    NAVY_TEXT_MUTED,
    NAVY_WAITING,
)

'''

MIXIN_CLASS_NAMES = {
    'shell': '_ShellMixin',
    'file': '_FileMixin',
    'mcp': '_McpMixin',
    'browser': '_BrowserMixin',
    'code': '_CodeMixin',
    'delegate': '_DelegateMixin',
    'terminal': '_TerminalMixin',
    'status': '_StatusMixin',
    'exploration': '_ExplorationMixin',
}


def _slice(lines: list[str], start: int, end: int) -> list[str]:
    return lines[start - 1 : end]


def _fix_read_symbols_staticmethod(body: list[str]) -> list[str]:
    out: list[str] = []
    for line in body:
        if line.strip() == 'def read_symbols_results(':
            out.append('    @staticmethod')
        out.append(line)
    return out


def main() -> None:
    text = SOURCE.read_text(encoding='utf-8')
    lines = text.splitlines()

    utils_body = _slice(lines, 31, 139)
    types_body = _slice(lines, 142, 211)

    TARGET.mkdir(parents=True, exist_ok=True)
    mixins_dir = TARGET / 'mixins'
    mixins_dir.mkdir(exist_ok=True)

    (TARGET / 'utils.py').write_text(
        UTILS_HEADER + '\n'.join(utils_body) + '\n',
        encoding='utf-8',
    )
    (TARGET / 'types.py').write_text(
        TYPES_HEADER + '\n'.join(types_body) + '\n',
        encoding='utf-8',
    )

    mixin_imports: list[str] = []
    mixin_bases: list[str] = []
    for name, (start, end) in MIXIN_RANGES.items():
        body = _slice(lines, start, end)
        if name == 'exploration':
            body = _fix_read_symbols_staticmethod(body)
        class_name = MIXIN_CLASS_NAMES[name]
        mixin_bases.append(class_name)
        mixin_imports.append(
            f'from backend.cli.event_rendering.unified_renderer.mixins.{name} import {class_name}'
        )
        body_text = '\n'.join(body).replace('ActivityRenderer', class_name)
        content = (
            f'"""Activity card builders — {name} domain."""\n\n'
            + MIXIN_IMPORTS[name]
            + f'\n\nclass {class_name}:\n'
            + body_text
            + '\n'
        )
        (mixins_dir / f'{name}.py').write_text(content, encoding='utf-8')

    (mixins_dir / '__init__.py').write_text(
        '"""Domain mixins for :class:`ActivityRenderer`."""\n',
        encoding='utf-8',
    )

    renderer_src = (
        '"""Composed activity card factory."""\n\n'
        'from __future__ import annotations\n\n' + '\n'.join(mixin_imports) + '\n\n\n'
        'class ActivityRenderer(\n'
        + ',\n'.join(f'    {base}' for base in mixin_bases)
        + ',\n):\n'
        '    """Factory for creating activity cards from agent events."""\n'
    )
    (TARGET / 'renderer.py').write_text(renderer_src, encoding='utf-8')

    init_src = (
        '"""Unified activity renderer for Grinta.\n\n'
        'Provides a single rendering pipeline that produces consistent output for both\n'
        'CLI (Rich) and TUI (Textual) modes. Uses activity cards with badges, verbs,\n'
        'and structured content instead of heavy bordered panels.\n'
        '"""\n\n'
        'from backend.cli.event_rendering.unified_renderer.renderer import ActivityRenderer\n'
        'from backend.cli.event_rendering.unified_renderer.types import (\n'
        '    ActivityCard,\n'
        '    ActivityLine,\n'
        ')\n\n'
        '__all__ = [\n'
        "    'ActivityCard',\n"
        "    'ActivityLine',\n"
        "    'ActivityRenderer',\n"
        ']\n'
    )
    (TARGET / '__init__.py').write_text(init_src, encoding='utf-8')

    SOURCE.unlink()
    print(f'split {SOURCE.name} -> {TARGET.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
