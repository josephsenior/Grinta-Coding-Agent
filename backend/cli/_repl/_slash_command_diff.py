"""Diff command and rendering for :class:`SlashCommandsMixin`.

Supports ``/diff [--stat|--name-only|--patch] [path]``. Wraps
``git diff`` and renders per-file foldable panels for ``--patch`` output.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from backend.cli._typing import SlashCommandsHost


def parse_diff_args(
    host: SlashCommandsHost,
    parsed: Any,
) -> tuple[str, list[str]] | None:
    mode = '--stat'
    paths: list[str] = []
    for arg in parsed.args:
        if arg in {'--stat', '--name-only', '--patch'}:
            mode = arg
            continue
        if arg.startswith('-'):
            host._warn(f'Usage: {host._usage(parsed.name)}')
            return None
        paths.append(arg)
    if len(paths) > 1:
        host._warn(f'Usage: {host._usage(parsed.name)}')
        return None
    return mode, paths


def build_diff_git_args(mode: str, paths: list[str]) -> list[str]:
    git_args = ['git', 'diff']
    if mode != '--patch':
        git_args.append(mode)
    if paths:
        git_args.extend(['--', paths[0]])
    return git_args


def run_git_diff(
    host: SlashCommandsHost,
    git_args: list[str],
    cwd: Path,
) -> str | None:
    try:
        completed = subprocess.run(
            git_args,
            capture_output=True,
            text=True,
            cwd=cwd,
            check=False,
        )
    except FileNotFoundError:
        if host._renderer is not None:
            host._renderer.add_system_message(
                '`git` not found on PATH; cannot show diff.',
                title='warning',
            )
        return None
    body = (completed.stdout or '').strip() or '(no changes)'
    if completed.stderr and completed.returncode != 0:
        body = f'git diff failed in {cwd}\n\n{completed.stderr.strip() or body}'
    return body


def parse_diff_files(diff_body: str) -> list[dict]:
    """Split a unified diff into per-file sections.

    Returns a list of dicts with keys: ``path``, ``lines``, ``added``, ``removed``.
    """
    import re

    files: list[dict] = []
    current: list[str] = []
    current_path = ''
    added = 0
    removed = 0

    for line in diff_body.split('\n'):
        if line.startswith('diff --git'):
            if current and current_path:
                files.append(
                    {
                        'path': current_path,
                        'lines': current,
                        'added': added,
                        'removed': removed,
                    }
                )
            current = [line]
            current_path = ''
            added = 0
            removed = 0
            m = re.match(r'diff --git a/(.*) b/.*', line)
            if m:
                current_path = m.group(1)
        else:
            current.append(line)
            if line.startswith('+') and not line.startswith('+++'):
                added += 1
            elif line.startswith('-') and not line.startswith('---'):
                removed += 1

    if current and current_path:
        files.append(
            {
                'path': current_path,
                'lines': current,
                'added': added,
                'removed': removed,
            }
        )

    return files


def _format_delta(added: int, removed: int) -> str:
    parts = []
    if added > 0:
        parts.append(f'+{added}')
    if removed > 0:
        parts.append(f'-{removed}')
    if not parts:
        return ''
    return f'  ({", ".join(parts)})'


def _build_diff_summary(files: list[dict]) -> str:
    file_count = len(files)
    total_added = sum(f['added'] for f in files)
    total_removed = sum(f['removed'] for f in files)
    summary = f'{file_count} file{"s" if file_count != 1 else ""} changed'
    if total_added > 0 or total_removed > 0:
        summary += _format_delta(total_added, total_removed)
    return summary


def _render_single_file_diff(renderer: Any, diff_body: str, summary: str) -> None:
    from rich.syntax import Syntax

    from backend.cli.theme import NAVY_BG, get_grinta_pygments_style

    syntax = Syntax(
        diff_body,
        lexer='diff',
        theme=get_grinta_pygments_style(),  # type: ignore[arg-type]
        word_wrap=True,
        padding=(1, 2),
        background_color=NAVY_BG,
        line_numbers=True,
    )
    renderer.add_system_message(f'{summary}\n\n{syntax}', title='diff')


def _render_file_panel(renderer: Any, f: dict) -> None:
    from rich import box
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.text import Text

    from backend.cli.theme import (
        CLR_CARD_BORDER,
        CLR_CARD_TITLE,
        NAVY_BG,
        get_grinta_pygments_style,
    )

    file_diff = '\n'.join(f['lines'])
    file_label = f['path']
    delta = _format_delta(f['added'], f['removed'])

    syntax = Syntax(
        file_diff,
        lexer='diff',
        theme=get_grinta_pygments_style(),  # type: ignore[arg-type]
        word_wrap=True,
        padding=(1, 2),
        background_color=NAVY_BG,
        line_numbers=True,
    )
    panel = Panel(
        syntax,
        title=Text(f'{file_label}{delta}', style=CLR_CARD_TITLE),
        title_align='left',
        border_style=CLR_CARD_BORDER,
        box=box.ROUNDED,
        padding=(0, 1),
    )
    if hasattr(renderer, 'add_renderable'):
        renderer.add_renderable(panel)
    else:
        renderer.add_system_message(
            f'[{file_label}]{delta}[/]\n\n{file_diff}',
            title='diff',
        )


def _render_multi_file_diff(renderer: Any, files: list[dict], summary: str) -> None:
    renderer.add_system_message(summary, title='diff')
    for f in files:
        _render_file_panel(renderer, f)


def renderer_render_diff(host: Any, renderer: Any, diff_body: str) -> None:
    """Render a patch diff with per-file foldable sections."""
    files = parse_diff_files(diff_body)
    summary = _build_diff_summary(files)
    if len(files) == 1:
        _render_single_file_diff(renderer, diff_body, summary)
        return
    _render_multi_file_diff(renderer, files, summary)


def cmd_diff(host: SlashCommandsHost, parsed: Any) -> bool:
    parsed_diff = parse_diff_args(host, parsed)
    if not isinstance(parsed_diff, tuple) or len(parsed_diff) != 2:
        return True  # type: ignore[unreachable]
    mode, paths = parsed_diff
    cwd = host._command_project_root()
    git_args = build_diff_git_args(mode, paths)
    body = run_git_diff(host, git_args, cwd)
    if body is None:
        return True
    if host._renderer is not None:
        if mode == '--patch' and body not in ('(no changes)', ''):
            renderer_render_diff(host, host._renderer, body)
        else:
            host._renderer.add_system_message(body, title='diff')
    return True
