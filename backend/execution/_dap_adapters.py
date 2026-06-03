"""DAP adapter auto-discovery (probe + build recipes per language).

Extracted from backend/execution/debugger.py to keep the parent module
under the per-file LOC budget. Provides the recipe registry, the
resolver that walks a recipe's probe + fallbacks, and the public
`detect_debug_adapters` summary used by diagnostics / UI.
"""

from __future__ import annotations

import shutil
import sys
from typing import Any

_LOGRECORD_EXTRA_FORBIDDEN: frozenset[str] | None = None


_DAP_ADAPTER_RECIPES: dict[str, dict[str, Any]] = {
    'go': {
        'probe': 'dlv',
        'build': lambda exe: [exe, 'dap'],
        'extensions': ('.go',),
    },
    'rust': {
        'probe': 'codelldb',
        'build': lambda exe: [exe, '--port', '0'],
        'fallbacks': [
            ('lldb-dap', lambda exe: [exe]),
            ('lldb-vscode', lambda exe: [exe]),
        ],
        'extensions': ('.rs',),
    },
    'cpp': {
        'probe': 'codelldb',
        'build': lambda exe: [exe, '--port', '0'],
        'fallbacks': [
            ('lldb-dap', lambda exe: [exe]),
            ('lldb-vscode', lambda exe: [exe]),
            ('OpenDebugAD7', lambda exe: [exe]),
        ],
        'extensions': ('.cpp', '.cc', '.cxx', '.hpp'),
    },
    'c': {
        'probe': 'lldb-dap',
        'build': lambda exe: [exe],
        'fallbacks': [
            ('codelldb', lambda exe: [exe, '--port', '0']),
            ('lldb-vscode', lambda exe: [exe]),
            ('OpenDebugAD7', lambda exe: [exe]),
        ],
        'extensions': ('.c', '.h'),
    },
    'csharp': {
        'probe': 'netcoredbg',
        'build': lambda exe: [exe, '--interpreter=vscode'],
        'extensions': ('.cs',),
    },
    'javascript': {
        'probe': 'js-debug-adapter',
        'build': lambda exe: [exe],
        'fallbacks': [
            ('js-debug-dap', lambda exe: [exe]),
            ('node-debug2', lambda exe: [exe]),
        ],
        'extensions': ('.js', '.mjs', '.cjs', '.jsx'),
    },
    'typescript': {
        'probe': 'js-debug-adapter',
        'build': lambda exe: [exe],
        'fallbacks': [
            ('js-debug-dap', lambda exe: [exe]),
            ('node-debug2', lambda exe: [exe]),
        ],
        'extensions': ('.ts', '.tsx'),
    },
    'java': {
        'probe': 'java-debug-adapter',
        'build': lambda exe: [exe],
        'extensions': ('.java',),
    },
    'ruby': {
        'probe': 'rdbg',
        'build': lambda exe: [exe, '--open', '--stop-at-load'],
        'extensions': ('.rb',),
    },
    'php': {
        'probe': 'php-debug-adapter',
        'build': lambda exe: [exe],
        'extensions': ('.php',),
    },
}


def _resolve_recipe(language: str) -> list[str] | None:
    """Walk a recipe's probe + fallbacks and return the first hit."""
    recipe = _DAP_ADAPTER_RECIPES.get(language)
    if not recipe:
        return None
    for probe, build in [
        (recipe['probe'], recipe['build']),
        *recipe.get('fallbacks', []),
    ]:
        exe = shutil.which(probe)
        if exe:
            return build(exe)
    return None


def _language_from_extension(ext: str) -> str | None:
    ext = ext.lower()
    for lang, recipe in _DAP_ADAPTER_RECIPES.items():
        if ext in recipe.get('extensions', ()):
            return lang
    return None


def detect_debug_adapters() -> list[dict[str, Any]]:
    """Probe PATH for known DAP adapters; useful for diagnostics / UI.

    Always reports Python as available because we ship ``debugpy`` as a
    wheel dependency. All other adapters are PATH-discovered.
    """
    results: list[dict[str, Any]] = [
        {
            'language': 'python',
            'adapter': 'debugpy',
            'available': True,
            'command': [sys.executable, '-m', 'debugpy.adapter'],
            'source': 'bundled',
        }
    ]
    for label, recipe in _DAP_ADAPTER_RECIPES.items():
        candidates = [(recipe['probe'], recipe['build'])]
        candidates.extend(recipe.get('fallbacks', []))
        found_command: list[str] | None = None
        found_probe: str | None = None
        for probe, build in candidates:
            exe = shutil.which(probe)
            if exe:
                found_command = build(exe)
                found_probe = probe
                break
        results.append(
            {
                'language': label,
                'adapter': found_probe or recipe['probe'],
                'available': found_command is not None,
                'command': found_command,
                'source': 'PATH',
            }
        )
    return results
