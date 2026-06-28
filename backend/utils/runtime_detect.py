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
* ``_DAP_ADAPTER_RECIPES`` — DAP adapters (debugpy, delve, codelldb, js-debug, …)

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
    # Human-readable install command for the user (e.g. "npm install -g pyright").
    install_hint: str | None = None
    # URL to the server's documentation / README.
    docs: str | None = None


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
        install_hint='pip install pyright',
        docs='https://github.com/microsoft/pyright/blob/main/README.md',
    ),
    'typescript': ToolSpec(
        name='typescript-language-server',
        language='typescript',
        extensions=('.ts', '.tsx', '.mts', '.cts'),
        command=('typescript-language-server', '--stdio'),
        install_hint='npm install -g typescript-language-server typescript',
        docs='https://github.com/typescript-language-server/typescript-language-server',
    ),
    'javascript': ToolSpec(
        name='typescript-language-server',
        language='javascript',
        extensions=('.js', '.jsx', '.mjs', '.cjs'),
        command=('typescript-language-server', '--stdio'),
        install_hint='npm install -g typescript-language-server typescript',
        docs='https://github.com/typescript-language-server/typescript-language-server',
    ),
    'deno': ToolSpec(
        name='deno',
        language='typescript',
        extensions=('.ts', '.tsx', '.js', '.jsx', '.mjs', '.mts', '.cts'),
        command=('deno', 'lsp'),
        probe=('deno', '--version'),
        docs='https://deno.land/manual@latest/tools/language_server',
    ),
    'json': ToolSpec(
        name='vscode-json-languageserver',
        language='json',
        extensions=('.json',),
        command=('vscode-json-languageserver', '--stdio'),
        install_hint='npm install -g vscode-json-languageserver',
        docs='https://github.com/hrsh7th/vscode-langservers-extracted',
    ),
    'go': ToolSpec(
        name='gopls',
        language='go',
        extensions=('.go',),
        command=('gopls',),
        install_hint='go install golang.org/x/tools/gopls@latest',
        docs='https://github.com/golang/tools/blob/master/gopls/README.md',
    ),
    'rust': ToolSpec(
        name='rust-analyzer',
        language='rust',
        extensions=('.rs',),
        command=('rust-analyzer',),
        install_hint='rustup component add rust-analyzer',
        docs='https://rust-analyzer.github.io/',
    ),
    'cpp': ToolSpec(
        name='clangd',
        language='cpp',
        extensions=('.c', '.cc', '.cpp', '.cxx', '.h', '.hpp', '.m', '.mm'),
        command=('clangd',),
        docs='https://clangd.llvm.org/installation',
    ),
    'lua': ToolSpec(
        name='lua-language-server',
        language='lua',
        extensions=('.lua',),
        command=('lua-language-server',),
        docs='https://github.com/LuaLS/lua-language-server',
    ),
    'ruby': ToolSpec(
        name='ruby-lsp',
        language='ruby',
        extensions=('.rb', '.rake', '.gemspec', '.ru'),
        command=('ruby-lsp',),
        probe=('ruby-lsp', '--version'),
        install_hint='gem install ruby-lsp',
        docs='https://github.com/Shopify/ruby-lsp',
    ),
    'php': ToolSpec(
        name='intelephense',
        language='php',
        extensions=('.php',),
        command=('intelephense', '--stdio'),
        install_hint='npm install -g intelephense',
        docs='https://github.com/nicolo-ribaudo/intelephense',
    ),
    'java': ToolSpec(
        name='jdtls',
        language='java',
        extensions=('.java',),
        command=('jdtls',),
        probe=('jdtls', '--help'),
        docs='https://github.com/eclipse/eclipse.jdt.ls',
    ),
    'kotlin': ToolSpec(
        name='kotlin-language-server',
        language='kotlin',
        extensions=('.kt', '.kts'),
        command=('kotlin-language-server',),
        probe=('kotlin-language-server', '--version'),
        docs='https://github.com/fwcd/kotlin-language-server',
    ),
    'csharp': ToolSpec(
        name='csharp-ls',
        language='csharp',
        extensions=('.cs', '.csx'),
        command=('csharp-ls',),
        probe=('csharp-ls', '--version'),
        install_hint='dotnet tool install -g csharp-ls',
        docs='https://github.com/razzmatazz/csharp-language-server',
    ),
    'fsharp': ToolSpec(
        name='fsautocomplete',
        language='fsharp',
        extensions=('.fs', '.fsi', '.fsx', '.fsscript'),
        command=('fsautocomplete',),
        probe=('fsautocomplete', '--version'),
        install_hint='dotnet tool install -g fsautocomplete',
        docs='https://github.com/fsharp/FsAutoComplete',
    ),
    'bash': ToolSpec(
        name='bash-language-server',
        language='bash',
        extensions=('.sh', '.bash', '.zsh', '.ksh'),
        command=('bash-language-server', 'start'),
        probe=('bash-language-server', '--version'),
        install_hint='npm install -g bash-language-server',
        docs='https://github.com/mads-hartmann/bash-language-server',
    ),
    'html': ToolSpec(
        name='vscode-html-language-server',
        language='html',
        extensions=('.html', '.htm'),
        command=('vscode-html-language-server', '--stdio'),
        install_hint='npm install -g vscode-html-languageserver-bin',
        docs='https://github.com/hrsh7th/vscode-langservers-extracted',
    ),
    'css': ToolSpec(
        name='vscode-css-language-server',
        language='css',
        extensions=('.css', '.scss', '.less'),
        command=('vscode-css-language-server', '--stdio'),
        install_hint='npm install -g vscode-css-languageserver-bin',
        docs='https://github.com/hrsh7th/vscode-langservers-extracted',
    ),
    'yaml': ToolSpec(
        name='yaml-language-server',
        language='yaml',
        extensions=('.yaml', '.yml'),
        command=('yaml-language-server', '--stdio'),
        install_hint='npm install -g yaml-language-server',
        docs='https://github.com/redhat-developer/yaml-language-server',
    ),
    'ansible': ToolSpec(
        name='ansible-language-server',
        language='ansible',
        extensions=('.yml', '.yaml'),
        command=('ansible-language-server', '--stdio'),
        probe=('ansible-language-server', '--version'),
        install_hint='npm install -g @ansible/ansible-language-server',
        docs='https://github.com/ansible/ansible-language-server',
    ),
    'helm': ToolSpec(
        name='helm-ls',
        language='helm',
        extensions=('.yaml', '.yml', '.tpl'),
        command=('helm-ls', 'serve'),
        probe=('helm-ls', 'version'),
        docs='https://github.com/mrjosh/helm-ls',
    ),
    'terraform': ToolSpec(
        name='terraform-ls',
        language='terraform',
        extensions=('.tf', '.tfvars'),
        command=('terraform-ls', 'serve'),
        probe=('terraform-ls', 'version'),
        docs='https://github.com/hashicorp/terraform-ls',
    ),
    'toml': ToolSpec(
        name='taplo',
        language='toml',
        extensions=('.toml',),
        command=('taplo', 'lsp', 'stdio'),
        probe=('taplo', '--version'),
        docs='https://github.com/tamasfe/taplo',
    ),
    'dart': ToolSpec(
        name='dart',
        language='dart',
        extensions=('.dart',),
        command=('dart', 'language-server'),
        probe=('dart', '--version'),
        docs='https://dart.dev/tools/language-server',
    ),
    'swift': ToolSpec(
        name='sourcekit-lsp',
        language='swift',
        extensions=('.swift',),
        command=('sourcekit-lsp',),
        docs='https://github.com/swiftlang/sourcekit-lsp',
    ),
    'zig': ToolSpec(
        name='zls',
        language='zig',
        extensions=('.zig', '.zon'),
        command=('zls',),
        probe=('zls', 'version'),
        docs='https://github.com/zigtools/zls',
    ),
    'haskell': ToolSpec(
        name='haskell-language-server',
        language='haskell',
        extensions=('.hs', '.lhs'),
        command=('haskell-language-server-wrapper', '--lsp'),
        probe=('haskell-language-server-wrapper', '--version'),
        docs='https://github.com/haskell/haskell-language-server',
    ),
    'elixir': ToolSpec(
        name='elixir-ls',
        language='elixir',
        extensions=('.ex', '.exs'),
        command=('elixir-ls',),
        docs='https://github.com/elixir-ls/elixir-ls',
    ),
    'erlang': ToolSpec(
        name='erlang_ls',
        language='erlang',
        extensions=('.erl', '.hrl'),
        command=('erlang_ls',),
        probe=('erlang_ls', 'version'),
        docs='https://github.com/erlang-ls/erlang_ls',
    ),
    'clojure': ToolSpec(
        name='clojure-lsp',
        language='clojure',
        extensions=('.clj', '.cljs', '.cljc', '.edn'),
        command=('clojure-lsp',),
        probe=('clojure-lsp', 'version'),
        docs='https://github.com/clojure-lsp/clojure-lsp',
    ),
    'gleam': ToolSpec(
        name='gleam',
        language='gleam',
        extensions=('.gleam',),
        command=('gleam', 'lsp'),
        probe=('gleam', '--version'),
        docs='https://github.com/gleam-lang/gleam',
    ),
    'vue': ToolSpec(
        name='vue-language-server',
        language='vue',
        extensions=('.vue',),
        command=('vue-language-server', '--stdio'),
        install_hint='npm install -g @vue/language-server',
        docs='https://github.com/vuejs/language-tools',
    ),
    'svelte': ToolSpec(
        name='svelteserver',
        language='svelte',
        extensions=('.svelte',),
        command=('svelteserver', '--stdio'),
        install_hint='npm install -g svelte-language-server',
        docs='https://github.com/sveltejs/language-tools',
    ),
    'astro': ToolSpec(
        name='astro-ls',
        language='astro',
        extensions=('.astro',),
        command=('astro-ls', '--stdio'),
        install_hint='npm install -g @astrojs/language-server',
        docs='https://github.com/withastro/language-tools',
    ),
    'graphql': ToolSpec(
        name='graphql-lsp',
        language='graphql',
        extensions=('.graphql', '.gql'),
        command=('graphql-lsp', 'server', '-m', 'stream'),
        probe=('graphql-lsp', '--version'),
        install_hint='npm install -g graphql-language-service-cli',
        docs='https://github.com/graphql/graphiql/tree/main/packages/graphql-language-service-cli',
    ),
    'sql': ToolSpec(
        name='sqls',
        language='sql',
        extensions=('.sql',),
        command=('sqls',),
        probe=('sqls', '--version'),
        docs='https://github.com/lighttiger2505/sqls',
    ),
    'latex': ToolSpec(
        name='texlab',
        language='latex',
        extensions=('.tex',),
        command=('texlab',),
        probe=('texlab', '--version'),
        docs='https://github.com/latex-lsp/texlab',
    ),
    'xml': ToolSpec(
        name='lemminx',
        language='xml',
        extensions=('.xml',),
        command=('lemminx',),
        docs='https://github.com/eclipse-lemminx/lemminx',
    ),
    'cmake': ToolSpec(
        name='cmake-language-server',
        language='cmake',
        extensions=('.cmake',),
        command=('cmake-language-server',),
        probe=('cmake-language-server', '--version'),
        install_hint='pip install cmake-language-server',
        docs='https://github.com/cmake-language-server/cmake-language-server',
    ),
    'dockerfile': ToolSpec(
        name='docker-langserver',
        language='dockerfile',
        extensions=('.dockerfile',),
        command=('docker-langserver', '--stdio'),
        probe=('docker-langserver', '--version'),
        install_hint='npm install -g dockerfile-language-server-nodejs',
        docs='https://github.com/rcjsuen/dockerfile-language-server-nodejs',
    ),
    'markdown': ToolSpec(
        name='marksman',
        language='markdown',
        extensions=('.md', '.markdown'),
        command=('marksman', 'server'),
        probe=('marksman', '--version'),
        docs='https://github.com/artempykh/marksman',
    ),
    'proto': ToolSpec(
        name='buf',
        language='proto',
        extensions=('.proto',),
        command=('buf', 'lsp', 'serve', '--timeout', '0'),
        probe=('buf', '--version'),
        docs='https://buf.build/docs/language-server/',
    ),
    'prisma': ToolSpec(
        name='prisma-language-server',
        language='prisma',
        extensions=('.prisma',),
        command=('prisma-language-server', '--stdio'),
        probe=('prisma-language-server', '--version'),
        install_hint='npm install -g @prisma/language-server',
        docs='https://github.com/prisma/language-tools',
    ),
    'nix': ToolSpec(
        name='nixd',
        language='nix',
        extensions=('.nix',),
        command=('nixd',),
        probe=('nixd', '--version'),
        docs='https://github.com/nix-community/nixd',
    ),
    'ocaml': ToolSpec(
        name='ocamllsp',
        language='ocaml',
        extensions=('.ml', '.mli'),
        command=('ocamllsp',),
        probe=('ocamllsp', '--version'),
        docs='https://github.com/ocaml/ocaml-lsp',
    ),
    'typst': ToolSpec(
        name='tinymist',
        language='typst',
        extensions=('.typ', '.typc'),
        command=('tinymist',),
        probe=('tinymist', '--version'),
        docs='https://github.com/Enter-tainer/tinymist',
    ),
    'razor': ToolSpec(
        name='rzls',
        language='razor',
        extensions=('.razor', '.cshtml'),
        command=('rzls',),
        probe=('rzls', '--version'),
        docs='https://github.com/dotnet/razor',
    ),
    'scala': ToolSpec(
        name='metals',
        language='scala',
        extensions=('.scala', '.sc'),
        command=('metals',),
        probe=('metals', '--version'),
        docs='https://scalameta.org/metals/',
    ),
    'solidity': ToolSpec(
        name='solidity-ls',
        language='solidity',
        extensions=('.sol',),
        command=('solidity-ls', '--stdio'),
        probe=('solidity-ls', '--version'),
        docs='https://github.com/ethereum/solidity/blob/develop/docs/miscellaneous.rst',
    ),
    'purescript': ToolSpec(
        name='purescript-language-server',
        language='purescript',
        extensions=('.purs',),
        command=('purescript-language-server', '--stdio'),
        probe=('purescript-language-server', '--version'),
        install_hint='npm install -g purescript-language-server',
        docs='https://github.com/nwolverson/purescript-language-server',
    ),
    'reason': ToolSpec(
        name='reason-language-server',
        language='reason',
        extensions=('.re', '.rei'),
        command=('reason-language-server',),
        probe=('reason-language-server', '--version'),
        docs='https://github.com/jaredly/reason-language-server',
    ),
    'rescript': ToolSpec(
        name='rescript-language-server',
        language='rescript',
        extensions=('.res', '.resi'),
        command=('rescript-language-server',),
        probe=('rescript-language-server', '--version'),
        install_hint='npm install -g @rescript/language-server',
        docs='https://github.com/rescript-lang/rescript-editor-support',
    ),
    'perl': ToolSpec(
        name='pls',
        language='perl',
        extensions=('.pl', '.pm', '.t'),
        command=('pls',),
        probe=('pls', '--version'),
        install_hint='cpan PLS',
        docs='https://github.com/bscan/PerlNavigator',
    ),
    'smithy': ToolSpec(
        name='smithy-language-server',
        language='smithy',
        extensions=('.smithy',),
        command=('smithy-language-server',),
        probe=('smithy-language-server', '--version'),
        docs='https://smithy.io',
    ),
    'fortran': ToolSpec(
        name='fortls',
        language='fortran',
        extensions=('.f', '.for', '.f90', '.f95', '.f03'),
        command=('fortls',),
        probe=('fortls', '--version'),
        install_hint='pip install fortls',
        docs='https://github.com/fortran-lang/fortls',
    ),
    'nim': ToolSpec(
        name='nimlangserver',
        language='nim',
        extensions=('.nim', '.nims'),
        command=('nimlangserver',),
        probe=('nimlangserver', '--version'),
        install_hint='pip install nimlangserver',
        docs='https://github.com/PMunch/nimlanguageclient',
    ),
    'crystal': ToolSpec(
        name='crystalline',
        language='crystal',
        extensions=('.cr',),
        command=('crystalline',),
        probe=('crystalline', '--version'),
        docs='https://github.com/elbywan/crystalline',
    ),
    'd': ToolSpec(
        name='serve-d',
        language='d',
        extensions=('.d',),
        command=('serve-d',),
        probe=('serve-d', '--version'),
        docs='https://github.com/Pure-D/serve-d',
    ),
    'lean': ToolSpec(
        name='lean',
        language='lean',
        extensions=('.lean',),
        command=('lean', '--server'),
        probe=('lean', '--version'),
        docs='https://github.com/leanprover/lean4',
    ),
    'idris': ToolSpec(
        name='idris2-lsp',
        language='idris',
        extensions=('.idr',),
        command=('idris2', 'lsp'),
        probe=('idris2', '--version'),
        docs='https://github.com/idris-lang/Idris2',
    ),
    'roc': ToolSpec(
        name='roc-lsp',
        language='roc',
        extensions=('.roc',),
        command=('roc', 'lsp'),
        probe=('roc', '--version'),
        docs='https://www.roc-lang.org/',
    ),
    'slint': ToolSpec(
        name='slint-lsp',
        language='slint',
        extensions=('.slint',),
        command=('slint-lsp',),
        probe=('slint-lsp', '--version'),
        docs='https://slint.dev/',
    ),
    'wgsl': ToolSpec(
        name='wgsl-analyzer',
        language='wgsl',
        extensions=('.wgsl',),
        command=('wgsl-analyzer',),
        probe=('wgsl-analyzer', '--version'),
        install_hint='cargo install wgsl_analyzer',
        docs='https://github.com/wgsl-analyzer/wgsl-analyzer',
    ),
    'vhdl': ToolSpec(
        name='vhdl-ls',
        language='vhdl',
        extensions=('.vhd', '.vhdl'),
        command=('vhdl_ls',),
        probe=('vhdl_ls', '--version'),
        install_hint='cargo install vhdl_ls',
        docs='https://github.com/VHDL-LS/rust_hdl',
    ),
    'systemverilog': ToolSpec(
        name='svls',
        language='systemverilog',
        extensions=('.sv', '.svh'),
        command=('svls',),
        probe=('svls', '--version'),
        install_hint='cargo install svls',
        docs='https://github.com/dalance/svls',
    ),
    'rego': ToolSpec(
        name='regal',
        language='rego',
        extensions=('.rego',),
        command=('regal', 'language-server'),
        probe=('regal', 'version'),
        install_hint='go install github.com/styrainc/regal/cmd/regal@latest',
        docs='https://github.com/StyraInc/regal',
    ),
    'openscad': ToolSpec(
        name='openscad-lsp',
        language='openscad',
        extensions=('.scad',),
        command=('openscad-lsp',),
        probe=('openscad-lsp', '--version'),
        install_hint='cargo install openscad-lsp',
        docs='https://github.com/openscad/openscad-language-server',
    ),
    'nickel': ToolSpec(
        name='nickel',
        language='nickel',
        extensions=('.ncl',),
        command=('nickel', 'lsp'),
        probe=('nickel', '--version'),
        docs='https://github.com/nickel-lang/nickel',
    ),
    'cairo': ToolSpec(
        name='cairo-language-server',
        language='cairo',
        extensions=('.cairo',),
        command=('cairo-language-server',),
        probe=('cairo-language-server', '--version'),
        docs='https://github.com/starkware-libs/cairo',
    ),
    'move': ToolSpec(
        name='move-analyzer',
        language='move',
        extensions=('.move',),
        command=('move-analyzer',),
        probe=('move-analyzer', '--version'),
        docs='https://github.com/move-language/move-analyzer',
    ),
    'pascal': ToolSpec(
        name='pasls',
        language='pascal',
        extensions=('.pas', '.pp'),
        command=('pasls',),
        probe=('pasls', '--version'),
        docs='https://github.com/nicolo-ribaudo/pasls',
    ),
    'futhark': ToolSpec(
        name='futhark-lsp',
        language='futhark',
        extensions=('.fut',),
        command=('futhark-lsp',),
        probe=('futhark-lsp', '--version'),
        docs='https://github.com/athas/futhark',
    ),
    'wat': ToolSpec(
        name='wasm-language-tools',
        language='wat',
        extensions=('.wat', '.wast'),
        command=('wasm-language-tools', 'server'),
        probe=('wasm-language-tools', '--version'),
        install_hint='npm install -g @vscode/wasm-wasi-lsp',
        docs='https://github.com/nicolo-ribaudo/vscode-wasm-wasi-lsp',
    ),
    'v': ToolSpec(
        name='v-analyzer',
        language='v',
        extensions=('.v',),
        command=('v-analyzer',),
        probe=('v-analyzer', '--version'),
        docs='https://github.com/nicolo-ribaudo/v-analyzer',
    ),
    'erg': ToolSpec(
        name='erg-language-server',
        language='erg',
        extensions=('.e', '.ej'),
        command=('erg-language-server',),
        probe=('erg-language-server', '--version'),
        docs='https://github.com/erg-lang/erg',
    ),
    'starlark': ToolSpec(
        name='starlark',
        language='starlark',
        extensions=('.bzl', '.star'),
        command=('starlark',),
        probe=('starlark', '--version'),
        docs='https://github.com/nicolo-ribaudo/starlark-lsp',
    ),
    'glsl': ToolSpec(
        name='glsl_analyzer',
        language='glsl',
        extensions=('.glsl', '.vert', '.frag', '.comp'),
        command=('glsl_analyzer',),
        probe=('glsl_analyzer', '--version'),
        docs='https://github.com/nicolo-ribaudo/glsl-analyzer',
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
        docs='https://github.com/JuliaEditorSupport/LanguageServer.jl',
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
