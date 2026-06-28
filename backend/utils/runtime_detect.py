"""Auto-detection of installed LSP servers and DAP debug adapters.

The agent ships with first-class support for navigating and debugging
many languages, but the actual language servers and debug adapters live
on the user's machine. This module probes the local environment once
per process to discover what is actually installed, so the agent never
has to ask the user to configure paths.

Two registries are exposed:

* ``CANONICAL_LSP_SERVERS`` — one language server per language (pyright for
  Python, gopls for Go, rust-analyzer for Rust, …).  No fallback chains,
  no priority tuples — each language has exactly one canonical server.
  Marker-disambiguated ecosystems (Deno, Ansible, Helm) are treated as
  distinct languages so they still get the right specialised server.
* ``DEBUG_ADAPTERS`` — DAP adapters (debugpy, delve, codelldb, js-debug, …)

IDE-style debugger labels (e.g. ``pwa-node``) are normalized via
:func:`backend.execution.dap.dap_aliases.normalize_debug_adapter_name` and
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
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from backend.core.logging.logger import app_logger as logger
from backend.execution.dap.dap_aliases import normalize_debug_adapter_name
from backend.utils.path_normalize import to_native_path, which_normalized

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
    # Command that installs the server when auto-install is enabled (Phase 2).
    install: tuple[str, ...] | None = None
    # Package manager / install strategy: "npm", "pip", "go", "cargo",
    # "gem", "rustup", "dotnet", "cpan", "binary" (manual binary release).
    install_method: str = 'binary'


@dataclass
class DetectedTool:
    """Runtime detection result for a ToolSpec."""

    spec: ToolSpec
    available: bool
    resolved_command: tuple[str, ...] = field(default_factory=tuple)
    detail: str = ''


# ── Canonical LSP registry ────────────────────────────────────────────────
#
# One server per language — keyed by language-resolution key.  For most
# languages the key equals the LSP languageId.  Marker-disambiguated
# ecosystems (deno, ansible, helm) use the ecosystem name as the key; their
# ToolSpec.language holds the actual languageId sent in didOpen.
#
# Servers shared across languages (e.g. typescript-language-server handles
# both TypeScript and JavaScript) appear once per language with the matching
# extensions and languageId.  Detection deduplicates by server name so the
# shared binary is probed only once.
CANONICAL_LSP_SERVERS: dict[str, ToolSpec] = {
    'python': ToolSpec(
        name='pyright-langserver',
        language='python',
        extensions=('.py', '.pyw', '.pyi'),
        command=('pyright-langserver', '--stdio'),
        probe=('pyright-langserver', '--version'),
        install=('npm', 'install', '-g', 'pyright'),
        install_method='npm',
    ),
    'typescript': ToolSpec(
        name='typescript-language-server',
        language='typescript',
        extensions=('.ts', '.tsx', '.mts', '.cts'),
        command=('typescript-language-server', '--stdio'),
        install=('npm', 'install', '-g', 'typescript-language-server', 'typescript'),
        install_method='npm',
    ),
    'javascript': ToolSpec(
        name='typescript-language-server',
        language='javascript',
        extensions=('.js', '.jsx', '.mjs', '.cjs'),
        command=('typescript-language-server', '--stdio'),
        install=('npm', 'install', '-g', 'typescript-language-server', 'typescript'),
        install_method='npm',
    ),
    'deno': ToolSpec(
        name='deno',
        language='typescript',
        extensions=('.ts', '.tsx', '.js', '.jsx', '.mjs', '.mts', '.cts'),
        command=('deno', 'lsp'),
        probe=('deno', '--version'),
        install_method='binary',
    ),
    'json': ToolSpec(
        name='vscode-json-languageserver',
        language='json',
        extensions=('.json',),
        command=('vscode-json-languageserver', '--stdio'),
        install=('npm', 'install', '-g', 'vscode-json-languageserver'),
        install_method='npm',
    ),
    'go': ToolSpec(
        name='gopls',
        language='go',
        extensions=('.go',),
        command=('gopls',),
        install=('go', 'install', 'golang.org/x/tools/gopls@latest'),
        install_method='go',
    ),
    'rust': ToolSpec(
        name='rust-analyzer',
        language='rust',
        extensions=('.rs',),
        command=('rust-analyzer',),
        install=('rustup', 'component', 'add', 'rust-analyzer'),
        install_method='rustup',
    ),
    'cpp': ToolSpec(
        name='clangd',
        language='cpp',
        extensions=('.c', '.cc', '.cpp', '.cxx', '.h', '.hpp', '.m', '.mm'),
        command=('clangd',),
        install_method='binary',
    ),
    'lua': ToolSpec(
        name='lua-language-server',
        language='lua',
        extensions=('.lua',),
        command=('lua-language-server',),
        install_method='binary',
    ),
    'ruby': ToolSpec(
        name='ruby-lsp',
        language='ruby',
        extensions=('.rb', '.rake', '.gemspec', '.ru'),
        command=('ruby-lsp',),
        probe=('ruby-lsp', '--version'),
        install=('gem', 'install', 'ruby-lsp'),
        install_method='gem',
    ),
    'php': ToolSpec(
        name='intelephense',
        language='php',
        extensions=('.php',),
        command=('intelephense', '--stdio'),
        install=('npm', 'install', '-g', 'intelephense'),
        install_method='npm',
    ),
    'java': ToolSpec(
        name='jdtls',
        language='java',
        extensions=('.java',),
        command=('jdtls',),
        probe=('jdtls', '--help'),
        install_method='binary',
    ),
    'kotlin': ToolSpec(
        name='kotlin-language-server',
        language='kotlin',
        extensions=('.kt', '.kts'),
        command=('kotlin-language-server',),
        probe=('kotlin-language-server', '--version'),
        install_method='binary',
    ),
    'csharp': ToolSpec(
        name='csharp-ls',
        language='csharp',
        extensions=('.cs', '.csx'),
        command=('csharp-ls',),
        probe=('csharp-ls', '--version'),
        install=('dotnet', 'tool', 'install', '-g', 'csharp-ls'),
        install_method='dotnet',
    ),
    'fsharp': ToolSpec(
        name='fsautocomplete',
        language='fsharp',
        extensions=('.fs', '.fsi', '.fsx', '.fsscript'),
        command=('fsautocomplete',),
        probe=('fsautocomplete', '--version'),
        install=('dotnet', 'tool', 'install', '-g', 'fsautocomplete'),
        install_method='dotnet',
    ),
    'bash': ToolSpec(
        name='bash-language-server',
        language='bash',
        extensions=('.sh', '.bash', '.zsh', '.ksh'),
        command=('bash-language-server', 'start'),
        probe=('bash-language-server', '--version'),
        install=('npm', 'install', '-g', 'bash-language-server'),
        install_method='npm',
    ),
    'html': ToolSpec(
        name='vscode-html-language-server',
        language='html',
        extensions=('.html', '.htm'),
        command=('vscode-html-language-server', '--stdio'),
        install=('npm', 'install', '-g', 'vscode-html-languageserver-bin'),
        install_method='npm',
    ),
    'css': ToolSpec(
        name='vscode-css-language-server',
        language='css',
        extensions=('.css', '.scss', '.less'),
        command=('vscode-css-language-server', '--stdio'),
        install=('npm', 'install', '-g', 'vscode-css-languageserver-bin'),
        install_method='npm',
    ),
    'yaml': ToolSpec(
        name='yaml-language-server',
        language='yaml',
        extensions=('.yaml', '.yml'),
        command=('yaml-language-server', '--stdio'),
        install=('npm', 'install', '-g', 'yaml-language-server'),
        install_method='npm',
    ),
    'ansible': ToolSpec(
        name='ansible-language-server',
        language='ansible',
        extensions=('.yml', '.yaml'),
        command=('ansible-language-server', '--stdio'),
        probe=('ansible-language-server', '--version'),
        install=('npm', 'install', '-g', '@ansible/ansible-language-server'),
        install_method='npm',
    ),
    'helm': ToolSpec(
        name='helm-ls',
        language='helm',
        extensions=('.yaml', '.yml', '.tpl'),
        command=('helm-ls', 'serve'),
        probe=('helm-ls', 'version'),
        install_method='binary',
    ),
    'terraform': ToolSpec(
        name='terraform-ls',
        language='terraform',
        extensions=('.tf', '.tfvars'),
        command=('terraform-ls', 'serve'),
        probe=('terraform-ls', 'version'),
        install_method='binary',
    ),
    'toml': ToolSpec(
        name='taplo',
        language='toml',
        extensions=('.toml',),
        command=('taplo', 'lsp', 'stdio'),
        probe=('taplo', '--version'),
        install_method='binary',
    ),
    'dart': ToolSpec(
        name='dart',
        language='dart',
        extensions=('.dart',),
        command=('dart', 'language-server'),
        probe=('dart', '--version'),
        install_method='binary',
    ),
    'swift': ToolSpec(
        name='sourcekit-lsp',
        language='swift',
        extensions=('.swift',),
        command=('sourcekit-lsp',),
        install_method='binary',
    ),
    'zig': ToolSpec(
        name='zls',
        language='zig',
        extensions=('.zig', '.zon'),
        command=('zls',),
        probe=('zls', 'version'),
        install_method='binary',
    ),
    'haskell': ToolSpec(
        name='haskell-language-server',
        language='haskell',
        extensions=('.hs', '.lhs'),
        command=('haskell-language-server-wrapper', '--lsp'),
        probe=('haskell-language-server-wrapper', '--version'),
        install_method='binary',
    ),
    'elixir': ToolSpec(
        name='elixir-ls',
        language='elixir',
        extensions=('.ex', '.exs'),
        command=('elixir-ls',),
        install_method='binary',
    ),
    'erlang': ToolSpec(
        name='erlang_ls',
        language='erlang',
        extensions=('.erl', '.hrl'),
        command=('erlang_ls',),
        probe=('erlang_ls', 'version'),
        install_method='binary',
    ),
    'clojure': ToolSpec(
        name='clojure-lsp',
        language='clojure',
        extensions=('.clj', '.cljs', '.cljc', '.edn'),
        command=('clojure-lsp',),
        probe=('clojure-lsp', 'version'),
        install_method='binary',
    ),
    'gleam': ToolSpec(
        name='gleam',
        language='gleam',
        extensions=('.gleam',),
        command=('gleam', 'lsp'),
        probe=('gleam', '--version'),
        install_method='binary',
    ),
    'vue': ToolSpec(
        name='vue-language-server',
        language='vue',
        extensions=('.vue',),
        command=('vue-language-server', '--stdio'),
        install=('npm', 'install', '-g', '@vue/language-server'),
        install_method='npm',
    ),
    'svelte': ToolSpec(
        name='svelteserver',
        language='svelte',
        extensions=('.svelte',),
        command=('svelteserver', '--stdio'),
        install=('npm', 'install', '-g', 'svelte-language-server'),
        install_method='npm',
    ),
    'astro': ToolSpec(
        name='astro-ls',
        language='astro',
        extensions=('.astro',),
        command=('astro-ls', '--stdio'),
        install=('npm', 'install', '-g', '@astrojs/language-server'),
        install_method='npm',
    ),
    'graphql': ToolSpec(
        name='graphql-lsp',
        language='graphql',
        extensions=('.graphql', '.gql'),
        command=('graphql-lsp', 'server', '-m', 'stream'),
        probe=('graphql-lsp', '--version'),
        install=('npm', 'install', '-g', 'graphql-language-service-cli'),
        install_method='npm',
    ),
    'sql': ToolSpec(
        name='sqls',
        language='sql',
        extensions=('.sql',),
        command=('sqls',),
        probe=('sqls', '--version'),
        install_method='binary',
    ),
    'latex': ToolSpec(
        name='texlab',
        language='latex',
        extensions=('.tex',),
        command=('texlab',),
        probe=('texlab', '--version'),
        install_method='binary',
    ),
    'xml': ToolSpec(
        name='lemminx',
        language='xml',
        extensions=('.xml',),
        command=('lemminx',),
        install_method='binary',
    ),
    'cmake': ToolSpec(
        name='cmake-language-server',
        language='cmake',
        extensions=('.cmake',),
        command=('cmake-language-server',),
        probe=('cmake-language-server', '--version'),
        install=('pip', 'install', 'cmake-language-server'),
        install_method='pip',
    ),
    'dockerfile': ToolSpec(
        name='docker-langserver',
        language='dockerfile',
        extensions=('.dockerfile',),
        command=('docker-langserver', '--stdio'),
        probe=('docker-langserver', '--version'),
        install=('npm', 'install', '-g', 'dockerfile-language-server-nodejs'),
        install_method='npm',
    ),
    'markdown': ToolSpec(
        name='marksman',
        language='markdown',
        extensions=('.md', '.markdown'),
        command=('marksman', 'server'),
        probe=('marksman', '--version'),
        install_method='binary',
    ),
    'proto': ToolSpec(
        name='buf',
        language='proto',
        extensions=('.proto',),
        command=('buf', 'lsp', 'serve', '--timeout', '0'),
        probe=('buf', '--version'),
        install_method='binary',
    ),
    'prisma': ToolSpec(
        name='prisma-language-server',
        language='prisma',
        extensions=('.prisma',),
        command=('prisma-language-server', '--stdio'),
        probe=('prisma-language-server', '--version'),
        install=('npm', 'install', '-g', '@prisma/language-server'),
        install_method='npm',
    ),
    'nix': ToolSpec(
        name='nixd',
        language='nix',
        extensions=('.nix',),
        command=('nixd',),
        probe=('nixd', '--version'),
        install_method='binary',
    ),
    'ocaml': ToolSpec(
        name='ocamllsp',
        language='ocaml',
        extensions=('.ml', '.mli'),
        command=('ocamllsp',),
        probe=('ocamllsp', '--version'),
        install_method='binary',
    ),
    'typst': ToolSpec(
        name='tinymist',
        language='typst',
        extensions=('.typ', '.typc'),
        command=('tinymist',),
        probe=('tinymist', '--version'),
        install_method='binary',
    ),
    'razor': ToolSpec(
        name='rzls',
        language='razor',
        extensions=('.razor', '.cshtml'),
        command=('rzls',),
        probe=('rzls', '--version'),
        install_method='binary',
    ),
    'scala': ToolSpec(
        name='metals',
        language='scala',
        extensions=('.scala', '.sc'),
        command=('metals',),
        probe=('metals', '--version'),
        install_method='binary',
    ),
    'solidity': ToolSpec(
        name='solidity-ls',
        language='solidity',
        extensions=('.sol',),
        command=('solidity-ls', '--stdio'),
        probe=('solidity-ls', '--version'),
        install_method='npm',
    ),
    'purescript': ToolSpec(
        name='purescript-language-server',
        language='purescript',
        extensions=('.purs',),
        command=('purescript-language-server', '--stdio'),
        probe=('purescript-language-server', '--version'),
        install=('npm', 'install', '-g', 'purescript-language-server'),
        install_method='npm',
    ),
    'reason': ToolSpec(
        name='reason-language-server',
        language='reason',
        extensions=('.re', '.rei'),
        command=('reason-language-server',),
        probe=('reason-language-server', '--version'),
        install_method='binary',
    ),
    'rescript': ToolSpec(
        name='rescript-language-server',
        language='rescript',
        extensions=('.res', '.resi'),
        command=('rescript-language-server',),
        probe=('rescript-language-server', '--version'),
        install=('npm', 'install', '-g', '@rescript/language-server'),
        install_method='npm',
    ),
    'perl': ToolSpec(
        name='pls',
        language='perl',
        extensions=('.pl', '.pm', '.t'),
        command=('pls',),
        probe=('pls', '--version'),
        install=('cpan', 'PLS'),
        install_method='cpan',
    ),
    'smithy': ToolSpec(
        name='smithy-language-server',
        language='smithy',
        extensions=('.smithy',),
        command=('smithy-language-server',),
        probe=('smithy-language-server', '--version'),
        install_method='binary',
    ),
    'fortran': ToolSpec(
        name='fortls',
        language='fortran',
        extensions=('.f', '.for', '.f90', '.f95', '.f03'),
        command=('fortls',),
        probe=('fortls', '--version'),
        install=('pip', 'install', 'fortls'),
        install_method='pip',
    ),
    'nim': ToolSpec(
        name='nimlangserver',
        language='nim',
        extensions=('.nim', '.nims'),
        command=('nimlangserver',),
        probe=('nimlangserver', '--version'),
        install=('pip', 'install', 'nimlangserver'),
        install_method='pip',
    ),
    'crystal': ToolSpec(
        name='crystalline',
        language='crystal',
        extensions=('.cr',),
        command=('crystalline',),
        probe=('crystalline', '--version'),
        install_method='binary',
    ),
    'd': ToolSpec(
        name='serve-d',
        language='d',
        extensions=('.d',),
        command=('serve-d',),
        probe=('serve-d', '--version'),
        install_method='binary',
    ),
    'lean': ToolSpec(
        name='lean',
        language='lean',
        extensions=('.lean',),
        command=('lean', '--server'),
        probe=('lean', '--version'),
        install_method='binary',
    ),
    'idris': ToolSpec(
        name='idris2-lsp',
        language='idris',
        extensions=('.idr',),
        command=('idris2', 'lsp'),
        probe=('idris2', '--version'),
        install_method='binary',
    ),
    'roc': ToolSpec(
        name='roc-lsp',
        language='roc',
        extensions=('.roc',),
        command=('roc', 'lsp'),
        probe=('roc', '--version'),
        install_method='binary',
    ),
    'slint': ToolSpec(
        name='slint-lsp',
        language='slint',
        extensions=('.slint',),
        command=('slint-lsp',),
        probe=('slint-lsp', '--version'),
        install_method='binary',
    ),
    'wgsl': ToolSpec(
        name='wgsl-analyzer',
        language='wgsl',
        extensions=('.wgsl',),
        command=('wgsl-analyzer',),
        probe=('wgsl-analyzer', '--version'),
        install=('cargo', 'install', 'wgsl_analyzer'),
        install_method='cargo',
    ),
    'vhdl': ToolSpec(
        name='vhdl-ls',
        language='vhdl',
        extensions=('.vhd', '.vhdl'),
        command=('vhdl_ls',),
        probe=('vhdl_ls', '--version'),
        install=('cargo', 'install', 'vhdl_ls'),
        install_method='cargo',
    ),
    'systemverilog': ToolSpec(
        name='svls',
        language='systemverilog',
        extensions=('.sv', '.svh'),
        command=('svls',),
        probe=('svls', '--version'),
        install=('cargo', 'install', 'svls'),
        install_method='cargo',
    ),
    'rego': ToolSpec(
        name='regal',
        language='rego',
        extensions=('.rego',),
        command=('regal', 'language-server'),
        probe=('regal', 'version'),
        install=('go', 'install', 'github.com/styrainc/regal/cmd/regal@latest'),
        install_method='go',
    ),
    'openscad': ToolSpec(
        name='openscad-lsp',
        language='openscad',
        extensions=('.scad',),
        command=('openscad-lsp',),
        probe=('openscad-lsp', '--version'),
        install=('cargo', 'install', 'openscad-lsp'),
        install_method='cargo',
    ),
    'nickel': ToolSpec(
        name='nickel',
        language='nickel',
        extensions=('.ncl',),
        command=('nickel', 'lsp'),
        probe=('nickel', '--version'),
        install_method='binary',
    ),
    'cairo': ToolSpec(
        name='cairo-language-server',
        language='cairo',
        extensions=('.cairo',),
        command=('cairo-language-server',),
        probe=('cairo-language-server', '--version'),
        install_method='binary',
    ),
    'move': ToolSpec(
        name='move-analyzer',
        language='move',
        extensions=('.move',),
        command=('move-analyzer',),
        probe=('move-analyzer', '--version'),
        install_method='binary',
    ),
    'pascal': ToolSpec(
        name='pasls',
        language='pascal',
        extensions=('.pas', '.pp'),
        command=('pasls',),
        probe=('pasls', '--version'),
        install_method='binary',
    ),
    'futhark': ToolSpec(
        name='futhark-lsp',
        language='futhark',
        extensions=('.fut',),
        command=('futhark-lsp',),
        probe=('futhark-lsp', '--version'),
        install_method='binary',
    ),
    'wat': ToolSpec(
        name='wasm-language-tools',
        language='wat',
        extensions=('.wat', '.wast'),
        command=('wasm-language-tools', 'server'),
        probe=('wasm-language-tools', '--version'),
        install=('npm', 'install', '-g', '@vscode/wasm-wasi-lsp'),
        install_method='npm',
    ),
    'v': ToolSpec(
        name='v-analyzer',
        language='v',
        extensions=('.v',),
        command=('v-analyzer',),
        probe=('v-analyzer', '--version'),
        install_method='binary',
    ),
    'erg': ToolSpec(
        name='erg-language-server',
        language='erg',
        extensions=('.e', '.ej'),
        command=('erg-language-server',),
        probe=('erg-language-server', '--version'),
        install_method='binary',
    ),
    'starlark': ToolSpec(
        name='starlark',
        language='starlark',
        extensions=('.bzl', '.star'),
        command=('starlark',),
        probe=('starlark', '--version'),
        install_method='binary',
    ),
    'glsl': ToolSpec(
        name='glsl_analyzer',
        language='glsl',
        extensions=('.glsl', '.vert', '.frag', '.comp'),
        command=('glsl_analyzer',),
        probe=('glsl_analyzer', '--version'),
        install_method='binary',
    ),
    'julia': ToolSpec(
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
        install_method='binary',
    ),
}

# Marker-disambiguated languages — their extensions are also claimed by a
# default language; the marker check in resolve_language_key decides which
# one wins.  Excluded from the default extension map below so the default
# language wins when no marker is present.
_MARKER_LANGUAGE_KEYS = frozenset({'deno', 'ansible', 'helm'})

# Build the default extension → language-key map from the non-marker specs.
_EXTENSION_TO_LANGUAGE_KEY: dict[str, str] = {}
for _key, _spec in CANONICAL_LSP_SERVERS.items():
    if _key in _MARKER_LANGUAGE_KEYS:
        continue
    for _ext in _spec.extensions:
        _EXTENSION_TO_LANGUAGE_KEY[_ext] = _key
del _key, _spec

# Extensions shared between a default language and marker-based alternatives.
_DENO_EXTENSIONS = frozenset(
    {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.mts', '.cts'}
)
_YAML_EXTENSIONS = frozenset({'.yml', '.yaml'})


def _unique_server_specs() -> tuple[ToolSpec, ...]:
    """Deduplicate canonical specs by server name for detection.

    Servers shared across languages (e.g. typescript-language-server) appear
    once per language in ``CANONICAL_LSP_SERVERS``; probing the same binary
    multiple times is wasted work.
    """
    seen: dict[str, ToolSpec] = {}
    for spec in CANONICAL_LSP_SERVERS.values():
        seen.setdefault(spec.name, spec)
    return tuple(seen.values())


def canonical_spec_for_extension(ext: str) -> ToolSpec | None:
    """Return the canonical ToolSpec for *ext*, or None if unsupported."""
    normalized = ext.lower()
    if not normalized.startswith('.'):
        normalized = f'.{normalized}'
    key = _EXTENSION_TO_LANGUAGE_KEY.get(normalized)
    if key is None:
        return None
    return CANONICAL_LSP_SERVERS.get(key)


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
    resolved = which_normalized(head)
    if resolved is not None:
        resolved = to_native_path(resolved)
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
            or which_normalized(probe_head) is not None
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
            _lsp_cache = _detect_all(_unique_server_specs())
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

    ctx = lsp_context_for_file(file_path, workspace_root=workspace_root)
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
    'CANONICAL_LSP_SERVERS',
    'DetectedTool',
    'ToolSpec',
    'canonical_spec_for_extension',
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
