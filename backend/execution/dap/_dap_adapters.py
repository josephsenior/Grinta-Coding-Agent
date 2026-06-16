"""DAP adapter auto-discovery (probe + build recipes per language).

Extracted from backend/execution/debugger.py to keep the parent module
under the per-file LOC budget. Provides the recipe registry, the
resolver that walks a recipe's probe + fallbacks, and the public
`detect_debug_adapters` summary used by diagnostics / UI.
"""

from __future__ import annotations

import importlib.util
import inspect
import shutil
import socket
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

_LOGRECORD_EXTRA_FORBIDDEN: frozenset[str] | None = None

_SUPPORTED_DAP_TRANSPORTS = frozenset({'stdio', 'tcp'})
_DAPTransport = str
_DAPBuild = Callable[..., list[str]]
_DAPCandidate = tuple[str, _DAPBuild, _DAPTransport]


@dataclass(frozen=True)
class DAPAdapterSpec:
    """Resolved debug adapter launch/connect details."""

    command: list[str]
    transport: str = 'stdio'
    host: str | None = None
    port: int | None = None


_DAP_ADAPTER_RECIPES: dict[str, dict[str, Any]] = {
    'go': {
        'probe': 'dlv',
        'build': lambda exe, port: [exe, 'dap', f'--listen=127.0.0.1:{port}'],
        'transport': 'tcp',
        'extensions': ('.go',),
    },
    'rust': {
        'probe': 'codelldb',
        'build': lambda exe, port: [exe, '--port', str(port)],
        'transport': 'tcp',
        'fallbacks': [
            ('lldb-dap', lambda exe: [exe], 'stdio'),
            ('lldb-vscode', lambda exe: [exe], 'stdio'),
        ],
        'extensions': ('.rs',),
    },
    'cpp': {
        'probe': 'codelldb',
        'build': lambda exe, port: [exe, '--port', str(port)],
        'transport': 'tcp',
        'fallbacks': [
            ('lldb-dap', lambda exe: [exe], 'stdio'),
            ('lldb-vscode', lambda exe: [exe], 'stdio'),
            ('OpenDebugAD7', lambda exe: [exe], 'stdio'),
        ],
        'extensions': ('.cpp', '.cc', '.cxx', '.hpp'),
    },
    'c': {
        'probe': 'lldb-dap',
        'build': lambda exe: [exe],
        'transport': 'stdio',
        'fallbacks': [
            ('codelldb', lambda exe, port: [exe, '--port', str(port)], 'tcp'),
            ('lldb-vscode', lambda exe: [exe], 'stdio'),
            ('OpenDebugAD7', lambda exe: [exe], 'stdio'),
        ],
        'extensions': ('.c', '.h'),
    },
    'csharp': {
        'probe': 'netcoredbg',
        'build': lambda exe: [exe, '--interpreter=vscode'],
        'transport': 'stdio',
        'extensions': ('.cs',),
    },
    'javascript': {
        'probe': 'js-debug-adapter',
        'build': lambda exe: [exe],
        'transport': 'stdio',
        'fallbacks': [
            ('js-debug-dap', lambda exe: [exe], 'stdio'),
            ('node-debug2', lambda exe: [exe], 'stdio'),
        ],
        'extensions': ('.js', '.mjs', '.cjs', '.jsx'),
    },
    'typescript': {
        'probe': 'js-debug-adapter',
        'build': lambda exe: [exe],
        'transport': 'stdio',
        'fallbacks': [
            ('js-debug-dap', lambda exe: [exe], 'stdio'),
            ('node-debug2', lambda exe: [exe], 'stdio'),
        ],
        'extensions': ('.ts', '.tsx'),
    },
    'java': {
        'probe': 'java-debug-adapter',
        'build': lambda exe: [exe],
        'transport': 'stdio',
        'extensions': ('.java',),
    },
    'ruby': {
        'probe': 'rdbg',
        'build': lambda exe: [exe, '--open', '--stop-at-load'],
        # ``rdbg --open`` is a TCP debug server, but not a direct DAP adapter
        # process that this client can currently drive without the VS Code
        # rdbg adapter layer.
        'transport': 'ruby-debug',
        'extensions': ('.rb',),
    },
    'php': {
        'probe': 'php-debug-adapter',
        'build': lambda exe: [exe],
        'transport': 'stdio',
        'extensions': ('.php',),
    },
}


def _recipe_candidates(recipe: dict[str, Any]) -> Iterable[_DAPCandidate]:
    """Yield a recipe's primary probe followed by fallbacks.

    Fallbacks historically used ``(probe, build)`` tuples. Continue accepting
    that shape and default it to stdio so third-party tests/extensions do not
    need to update in lockstep.
    """
    yield (
        recipe['probe'],
        recipe['build'],
        str(recipe.get('transport') or 'stdio'),
    )
    for entry in recipe.get('fallbacks', []):
        if len(entry) == 2:
            probe, build = entry
            transport = 'stdio'
        else:
            probe, build, transport = entry
        yield str(probe), build, str(transport)


def _reserve_local_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def _call_build(build: _DAPBuild, exe: str, port: int | None) -> list[str]:
    params = inspect.signature(build).parameters
    if len(params) >= 2:
        return build(exe, port)
    return build(exe)


def _build_adapter_spec(
    build: _DAPBuild, exe: str, transport: str, *, allocate_port: bool
) -> DAPAdapterSpec:
    port = _reserve_local_tcp_port() if transport == 'tcp' and allocate_port else None
    build_port = 0 if transport == 'tcp' and port is None else port
    command = _call_build(build, exe, build_port)
    if transport == 'tcp':
        return DAPAdapterSpec(
            command=command,
            transport='tcp',
            host='127.0.0.1',
            port=port,
        )
    return DAPAdapterSpec(command=command, transport=transport)


def _substitute_tcp_port(command: list[str], port: int) -> list[str]:
    return [
        part.replace('{port}', str(port)).replace('${port}', str(port))
        for part in command
    ]


def _command_has_tcp_port_placeholder(command: list[str]) -> bool:
    return any('{port}' in part or '${port}' in part for part in command)


def build_custom_adapter_spec(
    command: list[str],
    *,
    transport: str = 'stdio',
    host: str | None = None,
    port: int | None = None,
) -> DAPAdapterSpec:
    """Build a launch spec for user-provided adapter commands."""
    if transport not in _SUPPORTED_DAP_TRANSPORTS:
        raise ValueError(f'Unsupported DAP adapter transport: {transport}')
    if transport == 'tcp':
        if port is None and not _command_has_tcp_port_placeholder(command):
            raise ValueError(
                'TCP adapter_command without adapter_port must include {port}'
            )
        tcp_port = port if port is not None and port > 0 else _reserve_local_tcp_port()
        return DAPAdapterSpec(
            command=_substitute_tcp_port(command, tcp_port),
            transport='tcp',
            host=host or '127.0.0.1',
            port=tcp_port,
        )
    return DAPAdapterSpec(command=command, transport='stdio')


def _resolve_adapter_spec(
    language: str,
    *,
    supported_transports: frozenset[str] = _SUPPORTED_DAP_TRANSPORTS,
) -> DAPAdapterSpec | None:
    """Walk a recipe's probe + fallbacks and return the first supported hit."""
    recipe = _DAP_ADAPTER_RECIPES.get(language)
    if not recipe:
        return None
    for probe, build, transport in _recipe_candidates(recipe):
        if transport not in supported_transports:
            continue
        exe = shutil.which(probe)
        if exe:
            return _build_adapter_spec(build, exe, transport, allocate_port=True)
    return None


def _resolve_recipe(
    language: str,
    *,
    supported_transports: frozenset[str] = _SUPPORTED_DAP_TRANSPORTS,
) -> list[str] | None:
    """Backward-compatible command-only adapter resolver."""
    spec = _resolve_adapter_spec(language, supported_transports=supported_transports)
    return spec.command if spec is not None else None


def _unsupported_recipe_hint(language: str) -> str:
    """Return installed adapters for ``language`` that this client cannot use."""
    recipe = _DAP_ADAPTER_RECIPES.get(language)
    if not recipe:
        return ''
    hits: list[str] = []
    for probe, _build, transport in _recipe_candidates(recipe):
        if transport in _SUPPORTED_DAP_TRANSPORTS:
            continue
        if shutil.which(probe):
            hits.append(f'{probe} ({transport})')
    return ', '.join(hits)


def _language_from_extension(ext: str) -> str | None:
    ext = ext.lower()
    for lang, recipe in _DAP_ADAPTER_RECIPES.items():
        if ext in recipe.get('extensions', ()):
            return lang
    return None


def _debugpy_available() -> bool:
    try:
        return importlib.util.find_spec('debugpy.adapter') is not None
    except (ImportError, ValueError):
        return False


def detect_debug_adapters() -> list[dict[str, Any]]:
    """Probe PATH for known DAP adapters; useful for diagnostics / UI.

    Reports both raw availability and whether the adapter is auto-resolvable
    by this runtime. The client can speak stdio and DAP-over-TCP; other debug
    servers are detected for diagnostics without being advertised as directly
    usable by the ``debugger`` tool.
    """
    debugpy_ok = _debugpy_available()
    results: list[dict[str, Any]] = [
        {
            'language': 'python',
            'adapter': 'debugpy',
            'available': debugpy_ok,
            'auto_resolvable': debugpy_ok,
            'transport': 'stdio',
            'host': None,
            'port': None,
            'command': [sys.executable, '-m', 'debugpy.adapter']
            if debugpy_ok
            else None,
            'source': 'bundled',
        }
    ]
    for label, recipe in _DAP_ADAPTER_RECIPES.items():
        first_found: dict[str, Any] | None = None
        first_supported: dict[str, Any] | None = None
        for probe, build, transport in _recipe_candidates(recipe):
            exe = shutil.which(probe)
            if not exe:
                continue
            spec = _build_adapter_spec(build, exe, transport, allocate_port=False)
            candidate = {
                'adapter': probe,
                'command': spec.command,
                'transport': transport,
                'host': spec.host,
                'port': spec.port,
                'source': 'PATH',
            }
            if first_found is None:
                first_found = candidate
            if transport in _SUPPORTED_DAP_TRANSPORTS:
                first_supported = candidate
                break

        chosen = first_supported or first_found
        available = chosen is not None
        auto_resolvable = first_supported is not None
        transport = (
            chosen['transport']
            if chosen is not None
            else str(recipe.get('transport') or 'stdio')
        )
        adapter = chosen['adapter'] if chosen is not None else recipe['probe']
        command = chosen['command'] if chosen is not None else None
        unsupported_reason = ''
        if available and not auto_resolvable:
            unsupported_reason = (
                f'{adapter} was found, but it uses {transport} transport; '
                'this DAP client currently supports stdio and DAP-over-TCP '
                'adapters only.'
            )
        results.append(
            {
                'language': label,
                'adapter': adapter,
                'available': available,
                'auto_resolvable': auto_resolvable,
                'transport': transport,
                'host': chosen.get('host') if chosen is not None else None,
                'port': chosen.get('port') if chosen is not None else None,
                'command': command,
                'source': 'PATH',
                'unsupported_reason': unsupported_reason,
            }
        )
    return results
