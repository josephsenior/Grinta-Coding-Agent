"""Reorganize top-level backend/cli modules into subpackages."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / 'cli'

MOVES: dict[str, str] = {
    'hud.py': 'display/hud.py',
    'status_chrome.py': 'display/status_chrome.py',
    'reasoning_display.py': 'display/reasoning_display.py',
    'transcript.py': 'display/transcript.py',
    'notifications.py': 'display/notifications.py',
    'diff_renderer.py': 'display/diff_renderer.py',
    'tool_call_display.py': 'display/tool_call_display.py',
    'session_manager.py': 'session/session_manager.py',
    'sessions_cli.py': 'session/sessions_cli.py',
    'settings_tui.py': 'settings/settings_tui.py',
    'confirmation.py': 'settings/confirmation.py',
    'init_wizard.py': 'onboarding/init_wizard.py',
}

IMPORT_REPLACEMENTS: list[tuple[str, str]] = [
    ('backend.cli.hud', 'backend.cli.display.hud'),
    ('backend.cli.status_chrome', 'backend.cli.display.status_chrome'),
    ('backend.cli.reasoning_display', 'backend.cli.display.reasoning_display'),
    ('backend.cli.transcript', 'backend.cli.display.transcript'),
    ('backend.cli.notifications', 'backend.cli.display.notifications'),
    ('backend.cli.diff_renderer', 'backend.cli.display.diff_renderer'),
    ('backend.cli.tool_call_display', 'backend.cli.display.tool_call_display'),
    ('backend.cli.session_manager', 'backend.cli.session.session_manager'),
    ('backend.cli.sessions_cli', 'backend.cli.session.sessions_cli'),
    ('backend.cli.settings_tui', 'backend.cli.settings.settings_tui'),
    ('backend.cli.confirmation', 'backend.cli.settings.confirmation'),
    ('backend.cli.init_wizard', 'backend.cli.onboarding.init_wizard'),
]

PACKAGE_INITS = {
    'display': '"""CLI display layer — HUD, transcript, tool headlines."""\n',
    'session': '"""Session management and /sessions CLI."""\n',
    'settings': '"""Settings TUI and confirmation flows."""\n',
    'onboarding': '"""First-run init wizard."""\n',
}


def _move_files() -> None:
    for old, new in MOVES.items():
        src = CLI / old
        dst = CLI / new
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not src.exists():
            if dst.exists():
                continue
            raise FileNotFoundError(src)
        src.rename(dst)
        print(f'moved {old} -> {new}')


def _write_package_inits() -> None:
    for pkg, doc in PACKAGE_INITS.items():
        init = CLI / pkg / '__init__.py'
        if not init.exists():
            init.write_text(doc, encoding='utf-8')


def _rewrite_imports() -> None:
    roots = [ROOT, ROOT.parent / 'scripts', ROOT.parent / 'docs']
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob('*'):
            if path.suffix not in {'.py', '.md'}:
                continue
            if 'reorganize_cli_top_level.py' in path.name:
                continue
            text = path.read_text(encoding='utf-8')
            original = text
            for old, new in IMPORT_REPLACEMENTS:
                text = text.replace(old, new)
            if text != original:
                path.write_text(text, encoding='utf-8')
                print(f'updated imports in {path.relative_to(ROOT.parent)}')


def main() -> None:
    _move_files()
    _write_package_inits()
    _rewrite_imports()
    print('done')


if __name__ == '__main__':
    main()
