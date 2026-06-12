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


def _format_env_secret_line(name: str, value: str) -> str:
    key = name.strip()
    if not key:
        raise ValueError('Environment variable name is required')
    v = value.strip()
    if not v:
        return f'{key}=\n'
    if any(c in v for c in ' \t\n#"\'') or '$' in v:
        escaped = v.replace('\\', '\\\\').replace('"', '\\"')
        return f'{key}="{escaped}"\n'
    return f'{key}={v}\n'


def _format_llm_api_key_line(value: str) -> str:
    return _format_env_secret_line('LLM_API_KEY', value)


def _load_env_lines(env_path: Path) -> list[str]:
    if not env_path.is_file():
        return []
    return env_path.read_text(encoding='utf-8').splitlines(keepends=True)


def _upsert_env_key_lines(lines: list[str], key: str, line_out: str) -> list[str]:
    new_lines: list[str] = []
    replaced = False
    prefixes = (f'{key}=', f'export {key}=')
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


def _upsert_llm_api_key_lines(lines: list[str], line_out: str) -> list[str]:
    return _upsert_env_key_lines(lines, 'LLM_API_KEY', line_out)


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


def _update_process_env_key(name: str, api_key: str) -> None:
    stripped = api_key.strip()
    key = name.strip()
    if stripped and key:
        os.environ[key] = stripped


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


def persist_provider_api_key_to_dotenv(
    provider: str,
    api_key: str,
    *,
    settings_json_path: Path | None = None,
    update_process_environ: bool = True,
) -> Path:
    """Upsert a provider-specific API key in ``.env`` next to settings.json."""
    from backend.core.config.provider_config import provider_config_manager

    env_var = provider_config_manager.get_environment_variable(provider)
    if not env_var:
        env_var = f'{provider.strip().upper().replace("-", "_")}_API_KEY'
    settings_path = settings_json_path or _settings_path_default()
    env_path = settings_path.parent / '.env'
    line_out = _format_env_secret_line(env_var, api_key)

    lines = _load_env_lines(env_path)
    body = ''.join(_upsert_env_key_lines(lines, env_var, line_out))
    _write_env_file(env_path, body)

    if update_process_environ:
        _update_process_env_key(env_var, api_key)

    return env_path
