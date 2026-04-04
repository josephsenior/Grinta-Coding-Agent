#!/usr/bin/env python3
"""Plugin development server with hot-reload.

Provides a lightweight environment for developing and testing App
plugins without running the full agent + runtime stack.

Usage::

    # List discovered plugins
    python -m backend.scripts.dev.plugin_dev list

    # Validate all plugins
    python -m backend.scripts.dev.plugin_dev validate

    # Run a plugin's hooks with mock events (interactive)
    python -m backend.scripts.dev.plugin_dev test MyPlugin

    # Watch a plugin directory and reload on change
    python -m backend.scripts.dev.plugin_dev watch --dir ./my_plugins
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root is on path
_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _get_registry():
    """Import and return the plugin registry."""
    from backend.core.plugin import get_plugin_registry

    return get_plugin_registry()


def cmd_list(args: argparse.Namespace) -> None:
    """List all discovered plugins."""
    registry = _get_registry()
    plugins = registry.plugins
    if not plugins:
        print('No plugins discovered.')
        return

    print(f'\n{"Name":<30} {"Version":<10} {"API":<6} {"Hooks"}')
    print('─' * 70)
    for plugin in plugins:
        name = type(plugin).__name__
        version = getattr(plugin, 'version', '?')
        api = getattr(plugin, 'api_version', '?')
        hooks = []
        for method_name in [
            'on_action_pre',
            'on_action_post',
            'on_event',
            'on_session_start',
            'on_session_end',
            'on_llm_pre',
            'on_llm_post',
            'on_condense',
            'on_memory_recall',
            'on_tool_invoke',
        ]:
            method = getattr(plugin, method_name, None)
            if method and not _is_base_method(method):
                hooks.append(method_name.replace('on_', ''))
        hook_str = ', '.join(hooks) if hooks else '(none)'
        print(f'  {name:<28} {version:<10} {api:<6} {hook_str}')
    print()


def cmd_validate(args: argparse.Namespace) -> None:
    """Validate all discovered plugins."""
    registry = _get_registry()
    errors = registry.validate_all()
    if not errors:
        print('✓ All plugins passed validation.')
        return

    print(f'\n✗ {len(errors)} plugin validation error(s):\n')
    for plugin_name, error_list in errors.items():
        print(f'  {plugin_name}:')
        for err in error_list:
            print(f'    - {err}')
    print()
    sys.exit(1)


def cmd_test(args: argparse.Namespace) -> None:
    """Test a specific plugin with mock events."""
    import asyncio

    registry = _get_registry()
    target = args.plugin_name

    plugin = None
    for p in registry.plugins:
        if type(p).__name__ == target:
            plugin = p
            break

    if plugin is None:
        print(f"Plugin '{target}' not found. Available plugins:")
        for p in registry.plugins:
            print(f'  - {type(p).__name__}')
        sys.exit(1)

    print(f'\nTesting plugin: {type(plugin).__name__}')
    print('─' * 50)

    # Run through lifecycle hooks with mock data
    async def _run_tests():
        print('\n[1] on_session_start...')
        try:
            await _call_if_exists(plugin, 'on_session_start', 'test-session-001', {})
            print('    ✓ OK')
        except Exception as e:
            print(f'    ✗ Error: {e}')

        print('\n[2] on_llm_pre...')
        mock_messages = [{'role': 'user', 'content': 'Hello'}]
        try:
            result = await _call_if_exists(plugin, 'on_llm_pre', mock_messages)
            print(f'    ✓ OK (returned {len(result or mock_messages)} messages)')
        except Exception as e:
            print(f'    ✗ Error: {e}')

        print('\n[3] on_llm_post...')
        try:
            await _call_if_exists(
                plugin, 'on_llm_post', {'choices': [{'message': {'content': 'Hi!'}}]}
            )
            print('    ✓ OK')
        except Exception as e:
            print(f'    ✗ Error: {e}')

        print('\n[4] on_session_end...')
        try:
            await _call_if_exists(
                plugin, 'on_session_end', 'test-session-001', {'reason': 'test'}
            )
            print('    ✓ OK')
        except Exception as e:
            print(f'    ✗ Error: {e}')

        print('\n' + '─' * 50)
        print('Plugin test complete.')

    asyncio.run(_run_tests())


def _detect_changed_files(watch_dir: Path, last_mtimes: dict[str, float]) -> bool:
    """Detect changed .py files. Returns True if any changed."""
    changed = False
    for py_file in watch_dir.rglob('*.py'):
        mtime = py_file.stat().st_mtime
        key = str(py_file)
        if key not in last_mtimes:
            last_mtimes[key] = mtime
        elif last_mtimes[key] != mtime:
            last_mtimes[key] = mtime
            changed = True
            print(f'\n  Changed: {py_file.name}')
    return changed


def _reload_plugins() -> None:
    """Reload plugin discovery and validate. Prints status."""
    from backend.core import plugin as plugin_mod

    importlib.reload(plugin_mod)
    registry = plugin_mod.get_plugin_registry()
    print(f'  ✓ {len(registry.plugins)} plugin(s) loaded')
    errors = registry.validate_all()
    if errors:
        for name, errs in errors.items():
            for e in errs:
                print(f'    ✗ {name}: {e}')
    else:
        print('  ✓ All plugins valid')


def cmd_watch(args: argparse.Namespace) -> None:
    """Watch a directory for plugin file changes and reload."""
    watch_dir = Path(args.dir).resolve()
    if not watch_dir.exists():
        print(f'Directory not found: {watch_dir}')
        sys.exit(1)

    print(f'Watching {watch_dir} for changes... (Ctrl+C to stop)')
    last_mtimes: dict[str, float] = {}

    try:
        while True:
            if _detect_changed_files(watch_dir, last_mtimes):
                print('  Reloading plugins...')
                try:
                    _reload_plugins()
                except Exception as e:
                    print(f'  ✗ Reload error: {e}')
            time.sleep(1)
    except KeyboardInterrupt:
        print('\nStopped.')


# ── Utilities ───────────────────────────────────────────────────────────────


async def _call_if_exists(plugin: Any, method: str, *args: Any) -> Any:
    """Call a plugin method if it exists and handle sync/async."""
    import inspect

    fn = getattr(plugin, method, None)
    if fn is None:
        return None
    result = fn(*args)
    if inspect.isawaitable(result):
        return await result
    return result


def _is_base_method(method: Any) -> bool:
    """Check if a method is the default ABC implementation (no-op)."""
    qualname = getattr(method, '__qualname__', '')
    return 'AppPlugin.' in qualname


def main() -> None:
    parser = argparse.ArgumentParser(
        prog='plugin_dev',
        description='App plugin development tools',
    )
    sub = parser.add_subparsers(dest='command')

    sub.add_parser('list', help='List discovered plugins')
    sub.add_parser('validate', help='Validate all plugins')

    test_p = sub.add_parser('test', help='Test a specific plugin')
    test_p.add_argument('plugin_name', help='Plugin class name to test')

    watch_p = sub.add_parser('watch', help='Watch directory for plugin changes')
    watch_p.add_argument('--dir', default='.', help='Directory to watch')

    args = parser.parse_args()

    commands = {
        'list': cmd_list,
        'validate': cmd_validate,
        'test': cmd_test,
        'watch': cmd_watch,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
