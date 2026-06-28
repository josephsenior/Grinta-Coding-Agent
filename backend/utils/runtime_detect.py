"""Auto-detection of installed LSP servers and DAP debug adapters.

The agent ships with first-class support for navigating and debugging
many languages, but the actual language servers and debug adapters live
on the user's machine. This module probes the local environment once
per process to discover what is actually installed, so the agent never
has to ask the user to configure paths.

Two registries are exposed:

* ``LSP_SERVERS``   — language servers (pylsp, gopls, rust-analyzer, …)
* ``DEBUG_ADAPTERS`` — DAP adapters (debugpy, delve, codelldb, js-debug, …)

IDE-style debugger labels (e.g. ``pwa-node``) are normalized via
:func:`backend.utils.lsp.language_tool_aliases.normalize_debug_adapter_name` and
re-exported from this module for convenience.

Detection follows a cheap-to-expensive ladder:

1. For Python-hosted tools (``python -m <module>``): import the module and
   run the configured probe command — ``sys.executable`` alone is never
   treated as proof the module exists.
2. ``shutil.which`` for a standalone executable on PATH.
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

from backend.core.logging.logger import app_logger as logger
from backend.utils.lsp.language_tool_aliases import normalize_debug_adapter_name

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


# First matching available server wins for a file extension (tuple order matters).
# Per-file routing in :mod:`lsp_project_routing` may override try-order using
# workspace markers; Python always prefers pyright-langserver over pylsp.
LSP_SERVERS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name='pyright-langserver',
        language='python',
        extensions=('.py', '.pyw', '.pyi'),
        command=('pyright-langserver', '--stdio'),
        probe=('pyright-langserver', '--version'),
    ),
    ToolSpec(
        name='pylsp',
        language='python',
        extensions=('.py', '.pyw', '.pyi'),
        command=(sys.executable, '-m', 'pylsp'),
        probe=(sys.executable, '-m', 'pylsp', '--version'),
        python_module='pylsp',
    ),
    ToolSpec(
        name='typescript-language-server',
        language='typescript',
        extensions=('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.mts', '.cts'),
        command=('typescript-language-server', '--stdio'),
    ),
    ToolSpec(
        name='deno',
        language='typescript',
        extensions=('.ts', '.tsx', '.js', '.jsx', '.mjs', '.mts', '.cts'),
        command=('deno', 'lsp'),
        probe=('deno', '--version'),
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
        extensions=('.c', '.cc', '.cpp', '.cxx', '.h', '.hpp', '.m', '.mm'),
        command=('clangd',),
    ),
    ToolSpec(
        name='lua-language-server',
        language='lua',
        extensions=('.lua',),
        command=('lua-language-server',),
    ),
    ToolSpec(
        name='ruby-lsp',
        language='ruby',
        extensions=('.rb', '.rake', '.gemspec', '.ru'),
        command=('ruby-lsp',),
        probe=('ruby-lsp', '--version'),
    ),
    ToolSpec(
        name='solargraph',
        language='ruby',
        extensions=('.rb', '.rake', '.gemspec', '.ru'),
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
    ToolSpec(
        name='kotlin-language-server',
        language='kotlin',
        extensions=('.kt', '.kts'),
        command=('kotlin-language-server',),
        probe=('kotlin-language-server', '--version'),
    ),
    ToolSpec(
        name='csharp-ls',
        language='csharp',
        extensions=('.cs', '.csx'),
        command=('csharp-ls',),
        probe=('csharp-ls', '--version'),
    ),
    ToolSpec(
        name='omnisharp',
        language='csharp',
        extensions=('.cs',),
        command=('OmniSharp', '--languageserver'),
        probe=('OmniSharp', '--version'),
    ),
    ToolSpec(
        name='fsautocomplete',
        language='fsharp',
        extensions=('.fs', '.fsi', '.fsx', '.fsscript'),
        command=('fsautocomplete',),
        probe=('fsautocomplete', '--version'),
    ),
    ToolSpec(
        name='bash-language-server',
        language='bash',
        extensions=('.sh', '.bash', '.zsh', '.ksh'),
        command=('bash-language-server', 'start'),
        probe=('bash-language-server', '--version'),
    ),
    ToolSpec(
        name='vscode-html-language-server',
        language='html',
        extensions=('.html', '.htm'),
        command=('vscode-html-language-server', '--stdio'),
    ),
    ToolSpec(
        name='vscode-css-language-server',
        language='css',
        extensions=('.css', '.scss', '.less'),
        command=('vscode-css-language-server', '--stdio'),
    ),
    ToolSpec(
        name='yaml-language-server',
        language='yaml',
        extensions=('.yaml', '.yml'),
        command=('yaml-language-server', '--stdio'),
    ),
    ToolSpec(
        name='terraform-ls',
        language='terraform',
        extensions=('.tf', '.tfvars'),
        command=('terraform-ls', 'serve'),
        probe=('terraform-ls', 'version'),
    ),
    ToolSpec(
        name='taplo',
        language='toml',
        extensions=('.toml',),
        command=('taplo', 'lsp', 'stdio'),
        probe=('taplo', '--version'),
    ),
    ToolSpec(
        name='dart',
        language='dart',
        extensions=('.dart',),
        command=('dart', 'language-server'),
        probe=('dart', '--version'),
    ),
    ToolSpec(
        name='sourcekit-lsp',
        language='swift',
        extensions=('.swift',),
        command=('sourcekit-lsp',),
    ),
    ToolSpec(
        name='zls',
        language='zig',
        extensions=('.zig', '.zon'),
        command=('zls',),
        probe=('zls', 'version'),
    ),
    ToolSpec(
        name='haskell-language-server',
        language='haskell',
        extensions=('.hs', '.lhs'),
        command=('haskell-language-server-wrapper', '--lsp'),
        probe=('haskell-language-server-wrapper', '--version'),
    ),
    ToolSpec(
        name='elixir-ls',
        language='elixir',
        extensions=('.ex', '.exs'),
        command=('elixir-ls',),
    ),
    ToolSpec(
        name='erlang_ls',
        language='erlang',
        extensions=('.erl', '.hrl'),
        command=('erlang_ls',),
        probe=('erlang_ls', 'version'),
    ),
    ToolSpec(
        name='clojure-lsp',
        language='clojure',
        extensions=('.clj', '.cljs', '.cljc', '.edn'),
        command=('clojure-lsp',),
        probe=('clojure-lsp', 'version'),
    ),
    ToolSpec(
        name='gleam',
        language='gleam',
        extensions=('.gleam',),
        command=('gleam', 'lsp'),
        probe=('gleam', '--version'),
    ),
    ToolSpec(
        name='vue-language-server',
        language='vue',
        extensions=('.vue',),
        command=('vue-language-server', '--stdio'),
    ),
    ToolSpec(
        name='svelteserver',
        language='svelte',
        extensions=('.svelte',),
        command=('svelteserver', '--stdio'),
    ),
    ToolSpec(
        name='astro-ls',
        language='astro',
        extensions=('.astro',),
        command=('astro-ls', '--stdio'),
    ),
    ToolSpec(
        name='graphql-lsp',
        language='graphql',
        extensions=('.graphql', '.gql'),
        command=('graphql-lsp', 'server', '-m', 'stream'),
        probe=('graphql-lsp', '--version'),
    ),
    ToolSpec(
        name='sqls',
        language='sql',
        extensions=('.sql',),
        command=('sqls',),
        probe=('sqls', '--version'),
    ),
    ToolSpec(
        name='texlab',
        language='latex',
        extensions=('.tex',),
        command=('texlab',),
        probe=('texlab', '--version'),
    ),
    ToolSpec(
        name='lemminx',
        language='xml',
        extensions=('.xml',),
        command=('lemminx',),
    ),
    ToolSpec(
        name='cmake-language-server',
        language='cmake',
        extensions=('.cmake',),
        command=('cmake-language-server',),
        probe=('cmake-language-server', '--version'),
    ),
    ToolSpec(
        name='docker-langserver',
        language='dockerfile',
        extensions=('.dockerfile',),
        command=('docker-langserver', '--stdio'),
        probe=('docker-langserver', '--version'),
    ),
    ToolSpec(
        name='marksman',
        language='markdown',
        extensions=('.md', '.markdown'),
        command=('marksman', 'server'),
        probe=('marksman', '--version'),
    ),
    ToolSpec(
        name='buf',
        language='proto',
        extensions=('.proto',),
        command=('buf', 'lsp', 'serve', '--timeout', '0'),
        probe=('buf', '--version'),
    ),
    # ── Extended registry (probe-only; install tools on the host) ───────────
    ToolSpec(
        name='ruff',
        language='python',
        extensions=('.py', '.pyw', '.pyi'),
        command=('ruff', 'server'),
        probe=('ruff', '--version'),
    ),
    ToolSpec(
        name='basedpyright-langserver',
        language='python',
        extensions=('.py', '.pyw', '.pyi'),
        command=('basedpyright-langserver', '--stdio'),
        probe=('basedpyright-langserver', '--version'),
    ),
    ToolSpec(
        name='jedi-language-server',
        language='python',
        extensions=('.py', '.pyw', '.pyi'),
        command=('jedi-language-server',),
        probe=('jedi-language-server', '--version'),
    ),
    ToolSpec(
        name='eslint-language-server',
        language='javascript',
        extensions=(
            '.ts',
            '.tsx',
            '.js',
            '.jsx',
            '.mjs',
            '.cjs',
            '.mts',
            '.cts',
            '.vue',
            '.svelte',
            '.astro',
        ),
        command=('eslint-language-server', '--stdio'),
        probe=('eslint-language-server', '--version'),
    ),
    ToolSpec(
        name='oxlint',
        language='javascript',
        extensions=(
            '.ts',
            '.tsx',
            '.js',
            '.jsx',
            '.mjs',
            '.cjs',
            '.mts',
            '.cts',
            '.vue',
            '.svelte',
            '.astro',
        ),
        command=('oxlint', '--lsp'),
        probe=('oxlint', '--version'),
    ),
    ToolSpec(
        name='biome',
        language='javascript',
        extensions=(
            '.ts',
            '.tsx',
            '.js',
            '.jsx',
            '.mjs',
            '.cjs',
            '.mts',
            '.cts',
            '.vue',
            '.svelte',
            '.astro',
            '.json',
        ),
        command=('biome', 'lsp-proxy', '--stdio'),
        probe=('biome', '--version'),
    ),
    ToolSpec(
        name='flow',
        language='javascript',
        extensions=('.js', '.jsx', '.mjs', '.cjs'),
        command=('flow', 'lsp'),
        probe=('flow', 'version'),
    ),
    ToolSpec(
        name='prisma-language-server',
        language='prisma',
        extensions=('.prisma',),
        command=('prisma-language-server', '--stdio'),
        probe=('prisma-language-server', '--version'),
    ),
    ToolSpec(
        name='nixd',
        language='nix',
        extensions=('.nix',),
        command=('nixd',),
        probe=('nixd', '--version'),
    ),
    ToolSpec(
        name='nil',
        language='nix',
        extensions=('.nix',),
        command=('nil',),
        probe=('nil', '--version'),
    ),
    ToolSpec(
        name='ocamllsp',
        language='ocaml',
        extensions=('.ml', '.mli'),
        command=('ocamllsp',),
        probe=('ocamllsp', '--version'),
    ),
    ToolSpec(
        name='tinymist',
        language='typst',
        extensions=('.typ', '.typc'),
        command=('tinymist',),
        probe=('tinymist', '--version'),
    ),
    ToolSpec(
        name='rzls',
        language='razor',
        extensions=('.razor', '.cshtml'),
        command=('rzls',),
        probe=('rzls', '--version'),
    ),
    ToolSpec(
        name='metals',
        language='scala',
        extensions=('.scala', '.sc'),
        command=('metals',),
        probe=('metals', '--version'),
    ),
    ToolSpec(
        name='tailwindcss-language-server',
        language='tailwind',
        extensions=('.css', '.scss', '.less', '.html', '.htm', '.js', '.jsx', '.ts', '.tsx'),
        command=('tailwindcss-language-server', '--stdio'),
        probe=('tailwindcss-language-server', '--version'),
    ),
    ToolSpec(
        name='ansible-language-server',
        language='ansible',
        extensions=('.yml', '.yaml'),
        command=('ansible-language-server', '--stdio'),
        probe=('ansible-language-server', '--version'),
    ),
    ToolSpec(
        name='helm-ls',
        language='helm',
        extensions=('.yaml', '.yml', '.tpl'),
        command=('helm-ls', 'serve'),
        probe=('helm-ls', 'version'),
    ),
    ToolSpec(
        name='solidity-ls',
        language='solidity',
        extensions=('.sol',),
        command=('solidity-ls', '--stdio'),
        probe=('solidity-ls', '--version'),
    ),
    ToolSpec(
        name='purescript-language-server',
        language='purescript',
        extensions=('.purs',),
        command=('purescript-language-server', '--stdio'),
        probe=('purescript-language-server', '--version'),
    ),
    ToolSpec(
        name='reason-language-server',
        language='reason',
        extensions=('.re', '.rei'),
        command=('reason-language-server',),
        probe=('reason-language-server', '--version'),
    ),
    ToolSpec(
        name='rescript-language-server',
        language='rescript',
        extensions=('.res', '.resi'),
        command=('rescript-language-server',),
        probe=('rescript-language-server', '--version'),
    ),
    ToolSpec(
        name='pls',
        language='perl',
        extensions=('.pl', '.pm', '.t'),
        command=('pls',),
        probe=('pls', '--version'),
    ),
    ToolSpec(
        name='ltex-ls',
        language='latex',
        extensions=('.tex', '.md', '.markdown'),
        command=('ltex-ls',),
        probe=('ltex-ls', '--version'),
    ),
    ToolSpec(
        name='smithy-language-server',
        language='smithy',
        extensions=('.smithy',),
        command=('smithy-language-server',),
        probe=('smithy-language-server', '--version'),
    ),
    ToolSpec(
        name='fortls',
        language='fortran',
        extensions=('.f', '.for', '.f90', '.f95', '.f03'),
        command=('fortls',),
        probe=('fortls', '--version'),
    ),
    ToolSpec(
        name='nimlangserver',
        language='nim',
        extensions=('.nim', '.nims'),
        command=('nimlangserver',),
        probe=('nimlangserver', '--version'),
    ),
    ToolSpec(
        name='crystalline',
        language='crystal',
        extensions=('.cr',),
        command=('crystalline',),
        probe=('crystalline', '--version'),
    ),
    ToolSpec(
        name='serve-d',
        language='d',
        extensions=('.d',),
        command=('serve-d',),
        probe=('serve-d', '--version'),
    ),
    ToolSpec(
        name='lean',
        language='lean',
        extensions=('.lean',),
        command=('lean', '--server'),
        probe=('lean', '--version'),
    ),
    ToolSpec(
        name='idris2-lsp',
        language='idris',
        extensions=('.idr',),
        command=('idris2', 'lsp'),
        probe=('idris2', '--version'),
    ),
    ToolSpec(
        name='roc-lsp',
        language='roc',
        extensions=('.roc',),
        command=('roc', 'lsp'),
        probe=('roc', '--version'),
    ),
    ToolSpec(
        name='slint-lsp',
        language='slint',
        extensions=('.slint',),
        command=('slint-lsp',),
        probe=('slint-lsp', '--version'),
    ),
    ToolSpec(
        name='wgsl-analyzer',
        language='wgsl',
        extensions=('.wgsl',),
        command=('wgsl-analyzer',),
        probe=('wgsl-analyzer', '--version'),
    ),
    ToolSpec(
        name='vhdl-ls',
        language='vhdl',
        extensions=('.vhd', '.vhdl'),
        command=('vhdl_ls',),
        probe=('vhdl_ls', '--version'),
    ),
    ToolSpec(
        name='svls',
        language='systemverilog',
        extensions=('.sv', '.svh'),
        command=('svls',),
        probe=('svls', '--version'),
    ),
    ToolSpec(
        name='regal',
        language='rego',
        extensions=('.rego',),
        command=('regal', 'language-server'),
        probe=('regal', 'version'),
    ),
    ToolSpec(
        name='openscad-lsp',
        language='openscad',
        extensions=('.scad',),
        command=('openscad-lsp',),
        probe=('openscad-lsp', '--version'),
    ),
    ToolSpec(
        name='nickel',
        language='nickel',
        extensions=('.ncl',),
        command=('nickel', 'lsp'),
        probe=('nickel', '--version'),
    ),
    ToolSpec(
        name='cairo-language-server',
        language='cairo',
        extensions=('.cairo',),
        command=('cairo-language-server',),
        probe=('cairo-language-server', '--version'),
    ),
    ToolSpec(
        name='move-analyzer',
        language='move',
        extensions=('.move',),
        command=('move-analyzer',),
        probe=('move-analyzer', '--version'),
    ),
    ToolSpec(
        name='pasls',
        language='pascal',
        extensions=('.pas', '.pp'),
        command=('pasls',),
        probe=('pasls', '--version'),
    ),
    ToolSpec(
        name='futhark-lsp',
        language='futhark',
        extensions=('.fut',),
        command=('futhark-lsp',),
        probe=('futhark-lsp', '--version'),
    ),
    ToolSpec(
        name='wasm-language-tools',
        language='wat',
        extensions=('.wat', '.wast'),
        command=('wasm-language-tools', 'server'),
        probe=('wasm-language-tools', '--version'),
    ),
    ToolSpec(
        name='v-analyzer',
        language='v',
        extensions=('.v',),
        command=('v-analyzer',),
        probe=('v-analyzer', '--version'),
    ),
    ToolSpec(
        name='erg-language-server',
        language='erg',
        extensions=('.e', '.ej'),
        command=('erg-language-server',),
        probe=('erg-language-server', '--version'),
    ),
    ToolSpec(
        name='starlark',
        language='starlark',
        extensions=('.bzl', '.star'),
        command=('starlark',),
        probe=('starlark', '--version'),
    ),
    ToolSpec(
        name='glsl_analyzer',
        language='glsl',
        extensions=('.glsl', '.vert', '.frag', '.comp'),
        command=('glsl_analyzer',),
        probe=('glsl_analyzer', '--version'),
    ),
    ToolSpec(
        name='julials',
        language='julia',
        extensions=('.jl',),
        command=(
            'julia',
            '--startup-file=no',
            '--eval',
            'using LanguageServer; LanguageServer.runserver()',
        ),
        probe=('julia', '--version'),
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


def _python_hosted_module(spec: ToolSpec) -> str | None:
    """Return the importable module name for ``python -m`` LSP tools."""
    if spec.python_module is not None:
        return spec.python_module
    if (
        len(spec.command) >= 3
        and os.path.normcase(spec.command[0]) == os.path.normcase(sys.executable)
        and spec.command[1] == '-m'
    ):
        return spec.command[2]
    return None


def _run_probe_command(probe: tuple[str, ...]) -> bool:
    try:
        res = subprocess.run(
            list(probe),
            capture_output=True,
            timeout=_PROBE_TIMEOUT_SEC,
        )
        return res.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _probe_python_hosted(spec: ToolSpec, module: str) -> DetectedTool:
    try:
        res = subprocess.run(
            [sys.executable, '-c', f'import {module}'],
            capture_output=True,
            timeout=_PROBE_TIMEOUT_SEC,
        )
        if res.returncode != 0:
            return DetectedTool(
                spec=spec,
                available=False,
                detail=f'python module {module} not importable',
            )
    except (OSError, subprocess.TimeoutExpired):
        return DetectedTool(
            spec=spec, available=False, detail='python module probe failed'
        )

    if spec.probe is not None and not _run_probe_command(spec.probe):
        return DetectedTool(
            spec=spec,
            available=False,
            detail=f'probe command failed for {spec.name}',
        )

    return DetectedTool(
        spec=spec,
        available=True,
        resolved_command=tuple(spec.command),
        detail=f'python module {module} ready',
    )


def _probe(spec: ToolSpec) -> DetectedTool:
    """Best-effort presence check for a single tool."""
    module = _python_hosted_module(spec)
    if module is not None:
        return _probe_python_hosted(spec, module)

    head = spec.command[0]
    resolved = shutil.which(head)
    if resolved is not None:
        return DetectedTool(
            spec=spec,
            available=True,
            resolved_command=(resolved,) + tuple(spec.command[1:]),
            detail=f'found on PATH at {resolved}',
        )

    if spec.probe is not None:
        probe_head = spec.probe[0]
        probe_runnable = (
            os.path.normcase(probe_head) == os.path.normcase(sys.executable)
            or shutil.which(probe_head) is not None
        )
        if probe_runnable and _run_probe_command(spec.probe):
            return DetectedTool(
                spec=spec,
                available=True,
                resolved_command=tuple(spec.command),
                detail='probe command succeeded',
            )

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
        from backend.execution.server.debugger import detect_debug_adapters

        return detect_debug_adapters()
    except Exception as exc:
        logger.debug('runtime_detect: DAP detection failed: %r', exc)
        return []


# ── Convenience helpers ───────────────────────────────────────────────────


def lsp_command_for_file(
    file_path: str | Path,
    *,
    workspace_root: Path | None = None,
) -> tuple[str, ...] | None:
    """Return the resolved LSP command for a file path, or None."""
    from backend.utils.lsp.lsp_project_routing import lsp_context_for_file

    if workspace_root is not None:
        from pathlib import Path as _Path

        from backend.utils.lsp.lsp_project_routing import (
            find_project_root,
            resolve_lsp_command,
        )

        path = _Path(file_path)
        ext = path.suffix.lower()
        if not ext:
            return None
        root = workspace_root
        return resolve_lsp_command(
            ext,
            detect_lsp_servers(),
            LSP_SERVERS,
            workspace_root=root,
        )

    ctx = lsp_context_for_file(file_path)
    return ctx.command if ctx is not None else None


def lsp_command_for_extension(
    ext: str,
    *,
    workspace_root: Path | None = None,
) -> tuple[str, ...] | None:
    """Return the resolved LSP command for a file extension, or None."""
    from pathlib import Path as _Path

    normalized = ext.lower()
    if not normalized.startswith('.'):
        normalized = f'.{normalized}'
    root = workspace_root if workspace_root is not None else _Path.cwd()
    return lsp_command_for_file(
        _Path(f'_lsp_routing_placeholder{normalized}'),
        workspace_root=root,
    )


def has_any_lsp_server() -> bool:
    """True when at least one LSP server is available locally."""
    if os.getenv('GRINTA_DISABLE_LSP_DETECTION') == '1':
        return False
    return any(t.available for t in detect_lsp_servers().values())


def has_any_debug_adapter() -> bool:
    """True when at least one DAP adapter is usable by this runtime.

    Python (debugpy) is auto-detected when installed in the active environment
    (``pip install debugpy``). PATH probes may also find non-DAP debug servers;
    those are reported for diagnostics but do not make the ``debugger`` tool
    available unless they use a supported transport.
    """
    if os.getenv('GRINTA_DISABLE_DEBUGGER_DETECTION') == '1':
        return False
    return any(
        entry.get('auto_resolvable', entry.get('available'))
        for entry in detect_debug_adapters_summary()
    )


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
            f'{e["language"]}:{e["adapter"]}'
            for e in debug
            if e.get('auto_resolvable', e.get('available'))
        ),
        'debug_unsupported': sorted(
            f'{e["language"]}:{e["adapter"]}({e.get("transport", "unknown")})'
            for e in debug
            if e.get('available') and not e.get('auto_resolvable', e.get('available'))
        ),
        'debug_missing': sorted(
            f'{e["language"]}:{e["adapter"]}' for e in debug if not e.get('available')
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
    'lsp_command_for_file',
    'normalize_debug_adapter_name',
    'reset_detection_cache',
]
