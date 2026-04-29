"""Auto-detection of installed LSP servers and DAP debug adapters.

The agent ships with first-class support for navigating and debugging
many languages, but the actual language servers and debug adapters live
on the user's machine. This module probes the local environment once
per process to discover what is actually installed, so the agent never
has to ask the user to configure paths.

Two registries are exposed:

* ``LSP_SERVERS``   — language servers (pylsp, gopls, rust-analyzer, …)
* ``DEBUG_ADAPTERS`` — DAP adapters (debugpy, delve, codelldb, js-debug, …)

Detection follows a cheap-to-expensive ladder:

1. ``shutil.which`` for an executable on PATH (fast, no subprocess).
2. ``python -m <module> --version`` for Python-hosted tools.
3. Fallback ``--version`` / ``--help`` probe with a tight timeout.

Results are cached in module globals; tests can call
``reset_detection_cache()`` between runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Sequence

from backend.core.logger import app_logger as logger

# Probe timeout — kept tight; missing tools should fail-fast.
_PROBE_TIMEOUT_SEC = 3.0


@dataclass(frozen=True)
class ToolSpec:
    """Static description of an LSP server or DAP debug adapter."""

    name: str
    language: str
    extensions: tuple[str, ...]
    # The command that launches the tool over stdio.
    command: tuple[str, ...]
    # Optional override for the version-probe (defaults to command + --version).
    probe: tuple[str, ...] | None = None
    # If true, also attempt a ``python -m <module>`` style probe before failing.
    python_module: str | None = None


@dataclass
class DetectedTool:
    """Runtime detection result for a ToolSpec."""

    spec: ToolSpec
    available: bool
    resolved_command: tuple[str, ...] = field(default_factory=tuple)
    detail: str = ''


# ── Registries ────────────────────────────────────────────────────────────


LSP_SERVERS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name='pylsp',
        language='python',
        extensions=('.py', '.pyw'),
        command=(sys.executable, '-m', 'pylsp'),
        probe=(sys.executable, '-m', 'pylsp', '--version'),
        python_module='pylsp',
    ),
    ToolSpec(
        name='pyright-langserver',
        language='python',
        extensions=('.py', '.pyw'),
        command=('pyright-langserver', '--stdio'),
    ),
    ToolSpec(
        name='typescript-language-server',
        language='typescript',
        extensions=('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'),
        command=('typescript-language-server', '--stdio'),
    ),
    ToolSpec(
        name='vscode-json-languageserver',
        language='json',
        extensions=('.json',),
        command=('vscode-json-languageserver', '--stdio'),
    ),
    ToolSpec(
        name='gopls',
        language='go',
        extensions=('.go',),
        command=('gopls',),
    ),
    ToolSpec(
        name='rust-analyzer',
        language='rust',
        extensions=('.rs',),
        command=('rust-analyzer',),
    ),
    ToolSpec(
        name='clangd',
        language='cpp',
        extensions=('.c', '.cc', '.cpp', '.cxx', '.h', '.hpp'),
        command=('clangd',),
    ),
    ToolSpec(
        name='lua-language-server',
        language='lua',
        extensions=('.lua',),
        command=('lua-language-server',),
    ),
    ToolSpec(
        name='solargraph',
        language='ruby',
        extensions=('.rb',),
        command=('solargraph', 'stdio'),
        probe=('solargraph', '--version'),
    ),
    ToolSpec(
        name='intelephense',
        language='php',
        extensions=('.php',),
        command=('intelephense', '--stdio'),
    ),
    ToolSpec(
        name='jdtls',
        language='java',
        extensions=('.java',),
        command=('jdtls',),
        probe=('jdtls', '--help'),
    ),
)


# DAP adapters live in :mod:`backend.execution.debugger` (``_DAP_ADAPTER_RECIPES``
# + ``detect_debug_adapters``). We import lazily inside helpers below to avoid
# pulling DAP machinery during plain LSP queries.


# ── Detection cache ───────────────────────────────────────────────────────


_lock = threading.RLock()
_lsp_cache: dict[str, DetectedTool] | None = None


def reset_detection_cache() -> None:
    """Clear cached detection results (used by tests)."""
    global _lsp_cache
    with _lock:
        _lsp_cache = None


def _probe(spec: ToolSpec) -> DetectedTool:
    """Best-effort presence check for a single tool."""
    # Step 1: shutil.which on the head of the command.
    head = spec.command[0]
    resolved = shutil.which(head)
    if resolved is not None:
        return DetectedTool(
            spec=spec,
            available=True,
            resolved_command=(resolved,) + tuple(spec.command[1:]),
            detail=f'found on PATH at {resolved}',
        )

    # Step 2: python -m <module> probe for Python-hosted tools.
    if spec.python_module is not None:
        try:
            res = subprocess.run(
                [sys.executable, '-c', f'import {spec.python_module}'],
                capture_output=True,
                timeout=_PROBE_TIMEOUT_SEC,
            )
            if res.returncode == 0:
                return DetectedTool(
                    spec=spec,
                    available=True,
                    resolved_command=tuple(spec.command),
                    detail=f'python module {spec.python_module} importable',
                )
        except (OSError, subprocess.TimeoutExpired):
            pass

    # Step 3: explicit probe command (last resort).
    if spec.probe is not None and shutil.which(spec.probe[0]) is not None:
        try:
            res = subprocess.run(
                list(spec.probe),
                capture_output=True,
                timeout=_PROBE_TIMEOUT_SEC,
            )
            if res.returncode == 0:
                return DetectedTool(
                    spec=spec,
                    available=True,
                    resolved_command=tuple(spec.command),
                    detail='probe command succeeded',
                )
        except (OSError, subprocess.TimeoutExpired):
            pass

    return DetectedTool(spec=spec, available=False, detail='not found')


def _detect_all(specs: Sequence[ToolSpec]) -> dict[str, DetectedTool]:
    out: dict[str, DetectedTool] = {}
    for spec in specs:
        try:
            out[spec.name] = _probe(spec)
        except Exception as exc:  # never let detection crash callers
            logger.debug('runtime_detect: probe of %s raised %r', spec.name, exc)
            out[spec.name] = DetectedTool(spec=spec, available=False, detail=str(exc))
    return out


def detect_lsp_servers() -> dict[str, DetectedTool]:
    """Return the cached map of LSP server name → DetectedTool."""
    global _lsp_cache
    with _lock:
        if _lsp_cache is None:
            _lsp_cache = _detect_all(LSP_SERVERS)
        return _lsp_cache


def detect_debug_adapters_summary() -> list[dict]:
    """Return the canonical DAP adapter detection list.

    Thin pass-through to :func:`backend.execution.debugger.detect_debug_adapters`
    so callers don't need to know which module owns the registry.
    """
    try:
        from backend.execution.debugger import detect_debug_adapters

        return detect_debug_adapters()
    except Exception as exc:
        logger.debug('runtime_detect: DAP detection failed: %r', exc)
        return []


# ── Convenience helpers ───────────────────────────────────────────────────


def lsp_command_for_extension(ext: str) -> tuple[str, ...] | None:
    """Return the resolved LSP command for a file extension, or None."""
    ext = ext.lower()
    for tool in detect_lsp_servers().values():
        if tool.available and ext in tool.spec.extensions:
            return tool.resolved_command
    return None


def has_any_lsp_server() -> bool:
    """True when at least one LSP server is available locally."""
    if os.getenv('GRINTA_DISABLE_LSP_DETECTION') == '1':
        return False
    return any(t.available for t in detect_lsp_servers().values())


def has_any_debug_adapter() -> bool:
    """True when at least one DAP adapter is available locally.

    Python (debugpy) is bundled, so this should effectively always return
    True in a working install. The probe still runs because users can
    disable detection via ``GRINTA_DISABLE_DEBUGGER_DETECTION=1``.
    """
    if os.getenv('GRINTA_DISABLE_DEBUGGER_DETECTION') == '1':
        return False
    return any(entry.get('available') for entry in detect_debug_adapters_summary())


def detection_summary() -> dict[str, list[str]]:
    """Return a compact human/CLI-friendly summary of detection results."""
    debug = detect_debug_adapters_summary()
    return {
        'lsp_available': sorted(
            t.spec.name for t in detect_lsp_servers().values() if t.available
        ),
        'lsp_missing': sorted(
            t.spec.name for t in detect_lsp_servers().values() if not t.available
        ),
        'debug_available': sorted(
            f"{e['language']}:{e['adapter']}" for e in debug if e.get('available')
        ),
        'debug_missing': sorted(
            f"{e['language']}:{e['adapter']}" for e in debug if not e.get('available')
        ),
    }


__all__ = [
    'DetectedTool',
    'LSP_SERVERS',
    'ToolSpec',
    'detect_debug_adapters_summary',
    'detect_lsp_servers',
    'detection_summary',
    'has_any_debug_adapter',
    'has_any_lsp_server',
    'lsp_command_for_extension',
    'reset_detection_cache',
]
