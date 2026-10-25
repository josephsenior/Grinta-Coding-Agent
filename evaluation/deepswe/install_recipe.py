"""Exact runtime installation recipe shared by Pier and model-free diagnostics."""

import shlex

from evaluation.deepswe.pier_compat import (
    codex_npm_install_args,
    resilient_uv_tool_install,
)


def installation_steps(
    *,
    grinta_repo,
    grinta_commit,
    codex_version,
    allow_tree_sitter_bootstrap,
    tree_sitter_languages,
    preserve_task_toolchain=False,
    grinta_source=None,
):
    grinta_requirement = grinta_source or f'git+{grinta_repo}@{grinta_commit}'
    codex_npm_args = codex_npm_install_args(codex_version)
    root_install = (
        'if command -v apt-get >/dev/null; then '
        'apt-get update && apt-get install -y ca-certificates curl git; '
        'elif command -v apk >/dev/null; then apk add --no-cache ca-certificates curl git; '
        'elif command -v yum >/dev/null; then yum install -y ca-certificates curl git; '
        'else echo "A supported package manager is required" >&2; exit 1; fi'
    )
    if preserve_task_toolchain:
        root_install = (
            'command -v curl >/dev/null && command -v git >/dev/null && '
            'command -v node >/dev/null && command -v npm >/dev/null && '
            'test -r /etc/ssl/certs/ca-certificates.crt || '
            '{ echo "Shared setup requires preprovisioned curl/git/node/npm/CA certificates" >&2; exit 1; }'
        )
    parser_prefetch = ''
    if not allow_tree_sitter_bootstrap:
        prefetch_commands = [
            (
                'for grinta_prefetch_attempt in 1 2 3; do '
                f'"$grinta_python" -c {
                    shlex.quote(
                        "from tree_sitter_language_pack import manifest_languages, prefetch; "
                        f"language={language!r}; available=set(manifest_languages()); "
                        "assert language in available, f'unsupported tree-sitter language: {language}'; "
                        "prefetch([language])"
                    )
                } && break; '
                'if [ "$grinta_prefetch_attempt" -eq 3 ]; then exit 1; fi; '
                'sleep $((grinta_prefetch_attempt * 5)); '
                'done; '
            )
            for language in tree_sitter_languages
        ]
        parser_prefetch = (
            'grinta_python="$(head -n 1 "$(command -v grinta-deepswe)" | cut -c 3-)"; '
            + ''.join(prefetch_commands)
        )
    system_runtime_links = ''
    if not allow_tree_sitter_bootstrap:
        system_runtime_links = (
            'ln -sf "$(command -v codex)" /usr/local/bin/codex; '
            'ln -sf "$(command -v node)" /usr/local/bin/node; '
        )
    grinta_install = (
        'set -euo pipefail; '
        f'{resilient_uv_tool_install(grinta_requirement, preserve_existing_uv=preserve_task_toolchain)}'
        f'{parser_prefetch}'
        'grinta-deepswe --help >/dev/null'
    )
    codex_install = (
        'set -euo pipefail; '
        'curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash; '
        'export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; '
        'nvm install 22; '
        f'npm install -g {codex_npm_args}; '
        f'{system_runtime_links}'
        'codex --version'
    )
    if preserve_task_toolchain:
        codex_install = (
            'set -euo pipefail; '
            'prefix="$HOME/.local/share/grinta-comparison/codex"; '
            f'npm install --prefix "$prefix" -g {codex_npm_args}; '
            '"$prefix/bin/codex" --version'
        )
    return [
        {'user': 'root', 'run': root_install},
        {'user': 'agent', 'run': grinta_install},
        {'user': 'agent', 'run': codex_install},
    ]
