"""Manual smoke test using the configured ``settings.json`` LLM profile.

Reads ``settings.json`` (and ``.env`` when present) from the repository root,
creates a direct client, and sends a one-token completion request. Use this
when debugging provider routing or API keys for your local Grinta setup.

Run from the repository root::

    uv run python scripts/probe_llm_settings.py
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]


def redact(s: str | None) -> str | None:
    if s is None:
        return None
    s = str(s)
    if len(s) <= 12:
        return s[:4] + '...' + s[-4:]
    return s[:6] + '...' + s[-4:]


def main() -> int:
    _load_env_if_needed()
    cfg = _load_config()
    if cfg is None:
        return 2

    model, api_key, provider = _extract_config(cfg)
    if not model:
        print('llm_model is missing or empty in settings.json')
        return 2
    if not api_key:
        print('LLM API key is missing from settings.json and environment')
        return 2

    routed_model = _resolve_model(model, provider)
    print('Model:', model)
    print('Provider:', provider)
    print('API key (redacted):', redact(api_key))
    print('Effective model for client:', routed_model)

    return _create_and_test_client(routed_model, api_key)


def _load_config() -> dict | None:
    settings_path = _REPO_ROOT / 'settings.json'
    if not settings_path.is_file():
        print('settings.json not found at', settings_path)
        return None

    with settings_path.open('r', encoding='utf-8') as f:
        return json.load(f)


def _load_env_if_needed() -> None:
    env_path = _REPO_ROOT / '.env'
    if not env_path.is_file():
        return
    with env_path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                key, _, value = line.partition('=')
                if key and value and key not in os.environ:
                    os.environ[key] = value


def _extract_config(cfg: dict) -> tuple[str, str | None, str | None]:
    model = str(cfg.get('llm_model') or '').strip()
    raw_key = cfg.get('llm_api_key')
    provider = str(cfg.get('llm_provider') or '').strip() or None
    api_key = _resolve_api_key(raw_key)
    return model, api_key, provider


def _resolve_api_key(raw_key: Any) -> str | None:
    placeholder = '${LLM_API_KEY}'
    if (
        not raw_key
        or str(raw_key).strip() == ''
        or str(raw_key).strip() == placeholder
    ):
        return os.environ.get('LLM_API_KEY')
    return raw_key


def _resolve_model(model: str, provider: str | None) -> str:
    if provider and provider.lower() == 'lightning':
        if not model.startswith('openai/'):
            return f'openai/{model}'
    return model


def _print_rate_limit_headers(client: Any) -> None:
    """Make a lightweight request just to capture and print rate limit headers."""
    try:
        response = client.client.chat.completions.create(
            model=client.model_name,
            messages=[{'role': 'user', 'content': 'Hi'}],
            max_tokens=1,
        )
        headers = response._headers if hasattr(response, '_headers') else {}
        if not headers:
            response_headers = getattr(response, '_response', None)
            if response_headers:
                headers = dict(response_headers.headers)
            elif hasattr(response, 'headers'):
                headers = dict(getattr(response, 'headers', {}))
        print('\nRate Limit Headers:')
        print('-' * 40)
        for key in (
            'ratelimit-limit',
            'ratelimit-remaining',
            'ratelimit-reset',
            'x-ratelimit-limit-requests',
            'x-ratelimit-remaining-requests',
            'x-ratelimit-reset-requests',
        ):
            val = headers.get(key) if isinstance(headers, dict) else None
            if val is None:
                continue
            if key == 'ratelimit-reset':
                from datetime import datetime

                ts = int(val)
                dt = datetime.fromtimestamp(ts)
                print(f'  {key}: {val} (resets at {dt})')
            else:
                print(f'  {key}: {val}')
        print('-' * 40)
    except Exception as e:
        print(f'Could not fetch rate limit headers: {e}')


def _create_and_test_client(model: str, api_key: str) -> int:
    try:
        from backend.inference.direct_clients import get_direct_client

        client = get_direct_client(model, api_key)
        print('Client created:', type(client).__name__)

        _print_rate_limit_headers(client)

        messages = [{'role': 'user', 'content': 'Hello, say hi in one word.'}]
        print('Sending a short test completion request...')
        resp = client.completion(messages, max_tokens=1)
        print('Response:', resp)
        return 0

    except Exception as e:
        _print_exception_info(e)
        return 1


def _print_exception_info(e: Exception) -> None:
    print('Exception during LLM call:', type(e).__name__, str(e))
    print('\nTraceback:')
    traceback.print_exc()
    try:
        for a in ('status_code', 'code', 'body', 'llm_provider', 'model'):
            if hasattr(e, a):
                val = getattr(e, a)
                if isinstance(val, str) and len(val) > 0:
                    print(f'{a}:', redact(val))
                else:
                    print(f'{a}:', val)
    except Exception:
        pass


if __name__ == '__main__':
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    sys.exit(main())
