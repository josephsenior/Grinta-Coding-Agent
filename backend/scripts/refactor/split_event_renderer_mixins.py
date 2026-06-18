"""Split action/observation renderer mixins into domain subpackages."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ER = ROOT / 'cli' / 'event_rendering'

OBS_SOURCE = ER / 'observation_renderers_mixin.py'
ACT_SOURCE = ER / 'action_renderers_mixin.py'

OBS_TARGET = ER / 'observations'
ACT_TARGET = ER / 'actions'

OBS_CLASS = {
    'dispatch': '_ObsDispatchMixin',
    'think_browser': '_ObsThinkBrowserMixin',
    'shell': '_ObsShellMixin',
    'file': '_ObsFileMixin',
    'error': '_ObsErrorMixin',
    'status': '_ObsStatusMixin',
    'mcp': '_ObsMcpMixin',
    'terminal': '_ObsTerminalMixin',
    'exploration': '_ObsExplorationMixin',
    'misc': '_ObsMiscMixin',
}

ACT_CLASS = {
    'dispatch': '_ActionDispatchMixin',
    'message': '_ActionMessageMixin',
    'shell': '_ActionShellMixin',
    'file': '_ActionFileMixin',
    'mcp': '_ActionMcpMixin',
    'browser': '_ActionBrowserMixin',
    'exploration': '_ActionExplorationMixin',
    'terminal': '_ActionTerminalMixin',
    'meta': '_ActionMetaMixin',
}

# 1-based inclusive line ranges (method groups inside the mixin class).
OBS_RANGES: dict[str, list[tuple[int, int]]] = {
    'dispatch': [(193, 243)],
    'think_browser': [(245, 262)],
    'shell': [(263, 384)],
    'file': [(385, 426), (712, 724)],
    'error': [(427, 492)],
    'status': [(493, 711)],
    'mcp': [(725, 788)],
    'terminal': [(789, 844)],
    'exploration': [(845, 1062)],
    'misc': [(1063, 1163)],
}

ACT_RANGES: dict[str, list[tuple[int, int]]] = {
    'dispatch': [(118, 247)],
    'message': [(249, 424)],
    'shell': [(426, 463)],
    'file': [(465, 536)],
    'mcp': [(537, 567)],
    'browser': [(568, 615)],
    'exploration': [(616, 641)],
    'terminal': [(672, 750)],
    'meta': [(642, 671), (752, 875)],
}

OBS_MODULE_HELPERS = (134, 191)
OBS_SHARED_IMPORTS = (23, 119)
ACT_SHARED_IMPORTS = (21, 113)

TYPE_CHECKING_BLOCK = """if TYPE_CHECKING:
    from backend.cli._typing import ObservationRenderersHost

    _ObservationRenderersBase = ObservationRenderersHost
else:
    _ObservationRenderersBase = object
"""

ACT_TYPE_CHECKING_BLOCK = """if TYPE_CHECKING:
    from backend.cli._typing import ActionRenderersHost

    _ActionRenderersBase = ActionRenderersHost
else:
    _ActionRenderersBase = object
"""


def _slice(lines: list[str], start: int, end: int) -> list[str]:
    return lines[start - 1 : end]


def _extract_body(lines: list[str], ranges: list[tuple[int, int]]) -> list[str]:
    body: list[str] = []
    for start, end in ranges:
        body.extend(_slice(lines, start, end))
    return body


def _write_observations() -> list[str]:
    text = OBS_SOURCE.read_text(encoding='utf-8')
    lines = text.splitlines()
    OBS_TARGET.mkdir(parents=True, exist_ok=True)

    helpers = '\n'.join(_slice(lines, *OBS_MODULE_HELPERS))
    (OBS_TARGET / 'shell_helpers.py').write_text(
        '"""Shell output helpers for observation rendering."""\n\n'
        'from __future__ import annotations\n\n'
        'import json\n'
        'from typing import Any\n\n'
        'from rich.syntax import Syntax\n\n'
        'from backend.cli.theme import NAVY_BG, get_grinta_pygments_style\n\n'
        + helpers
        + '\n',
        encoding='utf-8',
    )

    shared = '\n'.join(_slice(lines, *OBS_SHARED_IMPORTS))
    mixin_names: list[str] = []
    for name, ranges in OBS_RANGES.items():
        class_name = OBS_CLASS[name]
        mixin_names.append(class_name)
        body = '\n'.join(_extract_body(lines, ranges))
        if name == 'dispatch':
            body = body.replace(
                'class ObservationRenderersMixin(_ObservationRenderersBase):',
                f'class {class_name}(_ObservationRenderersBase):',
            )
        else:
            body = f'class {class_name}(_ObservationRenderersBase):\n' + body
        content = (
            f'"""Observation renderers — {name} domain."""\n\n'
            'from __future__ import annotations\n\n'
            'import logging\n'
            'from typing import TYPE_CHECKING, Any, cast\n\n'
            + TYPE_CHECKING_BLOCK
            + '\n'
            + shared
            + '\n\n'
            + 'logger = logging.getLogger(__name__)\n\n'
            + body
            + '\n'
        )
        (OBS_TARGET / f'{name}.py').write_text(content, encoding='utf-8')

    compose_imports = '\n'.join(
        f'from backend.cli.event_rendering.observations.{n} import {OBS_CLASS[n]}'
        for n in OBS_RANGES
    )
    compose = (
        '"""Composed observation renderer mixin."""\n\n'
        'from __future__ import annotations\n\n' + compose_imports + '\n\n\n'
        'class ObservationRenderersMixin(\n'
        + ',\n'.join(f'    {OBS_CLASS[n]}' for n in OBS_RANGES)
        + ',\n):\n'
        '    """Per-observation ``_render_*_observation`` renderers + dispatch."""\n\n\n'
        "__all__ = ['ObservationRenderersMixin']\n"
    )
    (OBS_TARGET / '__init__.py').write_text(compose, encoding='utf-8')
    OBS_SOURCE.unlink()
    return mixin_names


def _write_actions() -> list[str]:
    text = ACT_SOURCE.read_text(encoding='utf-8')
    lines = text.splitlines()
    ACT_TARGET.mkdir(parents=True, exist_ok=True)

    shared = '\n'.join(_slice(lines, *ACT_SHARED_IMPORTS))
    for name, ranges in ACT_RANGES.items():
        class_name = ACT_CLASS[name]
        body = '\n'.join(_extract_body(lines, ranges))
        if name == 'dispatch':
            body = body.replace(
                'class ActionRenderersMixin(_ActionRenderersBase):',
                f'class {class_name}(_ActionRenderersBase):',
            )
        else:
            body = f'class {class_name}(_ActionRenderersBase):\n' + body
        content = (
            f'"""Action renderers — {name} domain."""\n\n'
            'from __future__ import annotations\n\n'
            'import re\n'
            'from typing import TYPE_CHECKING, Any, cast\n\n'
            + ACT_TYPE_CHECKING_BLOCK
            + '\n'
            + shared
            + '\n\n'
            + body
            + '\n'
        )
        (ACT_TARGET / f'{name}.py').write_text(content, encoding='utf-8')

    compose_imports = '\n'.join(
        f'from backend.cli.event_rendering.actions.{n} import {ACT_CLASS[n]}'
        for n in ACT_RANGES
    )
    compose = (
        '"""Composed action renderer mixin."""\n\n'
        'from __future__ import annotations\n\n' + compose_imports + '\n\n\n'
        'class ActionRenderersMixin(\n'
        + ',\n'.join(f'    {ACT_CLASS[n]}' for n in ACT_RANGES)
        + ',\n):\n'
        '    """Per-action ``_render_*_action`` renderers + dispatch."""\n\n\n'
        "__all__ = ['ActionRenderersMixin']\n"
    )
    (ACT_TARGET / '__init__.py').write_text(compose, encoding='utf-8')
    ACT_SOURCE.unlink()
    return list(ACT_CLASS.values())


def main() -> None:
    _write_observations()
    _write_actions()
    print('split observation + action renderer mixins')


if __name__ == '__main__':
    main()
