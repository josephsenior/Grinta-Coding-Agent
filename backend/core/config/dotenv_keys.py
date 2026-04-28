"""Persist LLM API secrets to repo-root ``.env`` (single source of truth).

``settings.json`` should only reference ``${LLM_API_KEY}``; the real value lives here.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from backend.core.app_paths import get_app_settings_root


def _settings_path_default() -> Path:
    return Path(get_app_settings_root()) / 'settings.json'


def _format_llm_api_key_line(value: str) -> str:
    v = value.strip()
    if not v:
        return 'LLM_API_KEY=\n'
    if any(c in v for c in ' \t\n#"\'') or '$' in v:
        escaped = v.replace('\\', '\\\\').replace('"', '\\"')
        return f'LLM_API_KEY="{escaped}"\n'
    return f'LLM_API_KEY={v}\n'


def _load_env_lines(env_path: Path) -> list[str]:
    if not env_path.is_file():
        return []
    return env_path.read_text(encoding='utf-8').splitlines(keepends=True)


def _upsert_llm_api_key_lines(lines: list[str], line_out: str) -> list[str]:
    new_lines: list[str] = []
    replaced = False
    prefixes = ('LLM_API_KEY=', 'export LLM_API_KEY=')
    for line in lines:
        stripped = line.lstrip()
        if any(stripped.startswith(prefix) for prefix in prefixes):
            if not replaced:
                new_lines.append(line_out)
                replaced = True
            continue
        new_lines.append(line)

    if replaced:
        return new_lines

    if new_lines and not new_lines[-1].endswith('\n'):
        new_lines[-1] += '\n'
    new_lines.append(line_out)
    return new_lines


def _write_env_file(env_path: Path, body: str) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=env_path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(body)
        os.replace(tmp, env_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _update_process_llm_api_key(api_key: str) -> None:
    stripped = api_key.strip()
    if stripped:
        os.environ['LLM_API_KEY'] = stripped


def persist_llm_api_key_to_dotenv(
    api_key: str,
    *,
    settings_json_path: Path | None = None,
    update_process_environ: bool = True,
) -> Path:
    """Upsert ``LLM_API_KEY`` in ``.env`` next to ``settings.json``.

    Args:
        api_key: Raw API key (stored only in ``.env``).
        settings_json_path: Repo ``settings.json`` path; defaults to canonical path.
        update_process_environ: If True, set ``os.environ['LLM_API_KEY']`` when non-empty.

    Returns:
        Path to the ``.env`` file written.
    """
    settings_path = settings_json_path or _settings_path_default()
    env_path = settings_path.parent / '.env'
    line_out = _format_llm_api_key_line(api_key)

    lines = _load_env_lines(env_path)
    body = ''.join(_upsert_llm_api_key_lines(lines, line_out))
    _write_env_file(env_path, body)

    if update_process_environ:
        _update_process_llm_api_key(api_key)

    return env_path
