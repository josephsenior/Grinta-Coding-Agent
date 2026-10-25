"""Narrow compatibility helpers for Pier-hosted DeepSWE trials."""

from __future__ import annotations

import shlex
from pathlib import Path


def normalize_shell_script_lf(path: Path) -> bool:
    """Rewrite CRLF shell-script bytes as LF, returning whether it changed."""
    original = path.read_bytes()
    normalized = original.replace(b'\r\n', b'\n')
    if normalized == original:
        return False
    path.write_bytes(normalized)
    return True


def codex_npm_install_args(version: str) -> str:
    """Return deterministic wrapper + Linux binary npm specs for Codex."""
    wrapper = f'@openai/codex@{version}'
    # The platform binary is an optional alias dependency. npm can omit it
    # after a slow registry fetch, leaving the wrapper unusable at runtime.
    linux_x64 = f'@openai/codex-linux-x64@npm:@openai/codex@{version}-linux-x64'
    return f'{shlex.quote(wrapper)} {shlex.quote(linux_x64)}'


def resilient_uv_tool_install(
    requirement: str,
    python_version: str = '3.12',
    *,
    preserve_existing_uv: bool = False,
) -> str:
    """Return a Docker-friendly uv install fragment resilient to slow indexes.

    The outer loop is intentional: uv keeps completed downloads in its cache
    between attempts within the same Docker layer, so one slow wheel does not
    force every dependency to be downloaded again.
    """
    quoted_requirement = shlex.quote(requirement)
    quoted_python = shlex.quote(python_version)
    bootstrap = (
        'curl --retry 5 --retry-all-errors --connect-timeout 30 --max-time 600 '
        '-LsSf https://astral.sh/uv/install.sh | sh; '
    )
    if preserve_existing_uv:
        bootstrap = 'command -v uv >/dev/null || { echo "Shared setup requires preprovisioned uv" >&2; exit 1; }; '
    return (
        bootstrap + 'export PATH="$HOME/.local/bin:$PATH"; '
        'export UV_HTTP_TIMEOUT=300 UV_HTTP_RETRIES=10; '
        'for grinta_install_attempt in 1 2 3; do '
        f'if uv tool install --python {quoted_python} --force {quoted_requirement}; then '
        'break; '
        'fi; '
        'if [ "$grinta_install_attempt" -eq 3 ]; then exit 1; fi; '
        'sleep $((grinta_install_attempt * 10)); '
        'done; '
    )
