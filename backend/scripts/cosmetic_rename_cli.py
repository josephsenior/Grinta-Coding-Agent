"""Remove leading underscores from CLI internal packages and module files."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'cli'
REPO = ROOT.parent

PACKAGE_RENAMES: list[tuple[str, str]] = [
    ('_tool_display', 'tool_display'),
    ('_event_renderer', 'event_rendering'),
]

REPL_FILE_RENAMES: list[tuple[str, str]] = [
    ('_run_helpers_bootstrap.py', 'run_helpers_bootstrap.py'),
    ('_run_helpers_dispatch.py', 'run_helpers_dispatch.py'),
    ('_run_helpers_prompt.py', 'run_helpers_prompt.py'),
    ('_session_lifecycle_confirm.py', 'session_lifecycle_confirm.py'),
    ('_session_lifecycle_resume.py', 'session_lifecycle_resume.py'),
    ('_session_lifecycle_wait.py', 'session_lifecycle_wait.py'),
    ('_slash_command_actions.py', 'slash_command_actions.py'),
    ('_slash_command_checkpoint.py', 'slash_command_checkpoint.py'),
    ('_slash_command_diff.py', 'slash_command_diff.py'),
    ('_slash_command_dispatch.py', 'slash_command_dispatch.py'),
    ('_slash_command_status.py', 'slash_command_status.py'),
    ('_slash_registry_clipboard.py', 'slash_registry_clipboard.py'),
    ('_slash_registry_commands.py', 'slash_registry_commands.py'),
    ('_slash_registry_help.py', 'slash_registry_help.py'),
    ('_slash_registry_models.py', 'slash_registry_models.py'),
    ('_slash_registry_parsing.py', 'slash_registry_parsing.py'),
    ('_slash_registry_prompt.py', 'slash_registry_prompt.py'),
    ('_slash_registry_terminal.py', 'slash_registry_terminal.py'),
]

ER_FILE_RENAMES: list[tuple[str, str]] = [
    ('_activity_mixin.py', 'activity_mixin.py'),
    ('_live_mixin.py', 'live_mixin.py'),
    ('_messages_mixin.py', 'messages_mixin.py'),
    ('_panels_mixin.py', 'panels_mixin.py'),
    ('_state_mixin.py', 'state_mixin.py'),
    ('_streaming_mixin.py', 'streaming_mixin.py'),
    ('_subscription_mixin.py', 'subscription_mixin.py'),
    ('_event_renderer_constants.py', 'renderer_constants.py'),
]

GLOBAL_IMPORT_SUBS: list[tuple[str, str]] = [
    ('backend.cli._tool_display', 'backend.cli.tool_display'),
    ('backend.cli._event_renderer', 'backend.cli.event_rendering'),
    ('backend.cli._repl', 'backend.cli.repl'),
]

ER_IMPORT_SUBS: list[tuple[str, str]] = [
    ('.error_categories._matchers', '.error_categories.matchers'),
    ('._activity_mixin', '.activity_mixin'),
    ('._live_mixin', '.live_mixin'),
    ('._messages_mixin', '.messages_mixin'),
    ('._panels_mixin', '.panels_mixin'),
    ('._state_mixin', '.state_mixin'),
    ('._streaming_mixin', '.streaming_mixin'),
    ('._subscription_mixin', '.subscription_mixin'),
    ('._event_renderer_constants', '.renderer_constants'),
]

# After repl.py becomes repl/session.py, test patches must target session.
SESSION_PATCH_SUBS: list[tuple[str, str]] = [
    ('backend.cli.repl.get_current_model', 'backend.cli.repl.session.get_current_model'),
    ('backend.cli.repl.load_app_config', 'backend.cli.repl.session.load_app_config'),
    (
        'backend.cli.repl._supports_prompt_session',
        'backend.cli.repl.session._supports_prompt_session',
    ),
    (
        'backend.cli.repl._prompt_toolkit_available',
        'backend.cli.repl.session._prompt_toolkit_available',
    ),
]


def _rename_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return
    if dst.exists():
        src.unlink()
    else:
        src.rename(dst)
        print(f'renamed {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}')


def _merge_repl_package() -> None:
    repl_py = CLI / 'repl.py'
    repl_dir = CLI / 'repl'
    old_repl = CLI / '_repl'

    if repl_dir.exists() and not old_repl.exists() and not repl_py.exists():
        print('repl package already migrated')
        return

    repl_dir.mkdir(exist_ok=True)

    if repl_py.exists():
        _rename_file(repl_py, repl_dir / 'session.py')

    if old_repl.exists():
        for path in sorted(old_repl.iterdir()):
            if path.name == '__init__.py':
                continue
            target_name = path.name
            for old, new in REPL_FILE_RENAMES:
                if path.name == old:
                    target_name = new
                    break
            _rename_file(path, repl_dir / target_name)
        old_init = old_repl / '__init__.py'
        if old_init.exists():
            old_init.unlink()
        try:
            old_repl.rmdir()
        except OSError:
            pass

    init = repl_dir / '__init__.py'
    init.write_text(
        '"""REPL session, slash commands, and run helpers."""\n\n'
        'from backend.cli.repl.session import Repl\n\n'
        '__all__ = ["Repl"]\n',
        encoding='utf-8',
    )


def _rename_packages() -> None:
    for old, new in PACKAGE_RENAMES:
        src = CLI / old
        dst = CLI / new
        if src.exists():
            if dst.exists():
                raise RuntimeError(f'both {old} and {new} exist')
            src.rename(dst)
            print(f'package {old} -> {new}')


def _rename_er_files() -> None:
    er = CLI / 'event_rendering'
    if not er.exists():
        return
    for old, new in ER_FILE_RENAMES:
        _rename_file(er / old, er / new)
    _rename_file(er / 'error_categories' / '_matchers.py', er / 'error_categories' / 'matchers.py')


def _repl_module_subs() -> list[tuple[str, str]]:
    subs: list[tuple[str, str]] = []
    for old, new in REPL_FILE_RENAMES:
        old_mod = old.removesuffix('.py')
        new_mod = new.removesuffix('.py')
        subs.append((f'backend.cli.repl.{old_mod}', f'backend.cli.repl.{new_mod}'))
        subs.append(
            (
                f'from backend.cli.repl import {old_mod}',
                f'import backend.cli.repl.{new_mod}',
            )
        )
    return subs


def _rewrite_text(text: str) -> str:
    for old, new in GLOBAL_IMPORT_SUBS:
        text = text.replace(old, new)
    for old, new in ER_IMPORT_SUBS:
        text = text.replace(old, new)
    for old, new in _repl_module_subs():
        text = text.replace(old, new)
    for old, new in SESSION_PATCH_SUBS:
        text = text.replace(old, new)
    return text


def _rewrite_tree() -> None:
    skip_names = {'cosmetic_rename_cli.py', 'split_config_manager.py'}
    bases = [ROOT, REPO / 'docs']
    for base in bases:
        if not base.exists():
            continue
        for path in base.rglob('*'):
            if path.suffix not in {'.py', '.md'}:
                continue
            if path.name in skip_names:
                continue
            text = path.read_text(encoding='utf-8')
            new_text = _rewrite_text(text)
            if new_text != text:
                path.write_text(new_text, encoding='utf-8')
                print(f'updated {path.relative_to(REPO)}')


def main() -> None:
    _merge_repl_package()
    _rename_packages()
    _rename_er_files()
    _rewrite_tree()
    print('cosmetic rename complete')


if __name__ == '__main__':
    main()
