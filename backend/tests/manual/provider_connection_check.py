"""Manual smoke test for a cloud LLM provider connection.

Run from the repo root with the matching API key in the environment or ``.env``::

    uv run python backend/tests/manual/provider_connection_check.py vercel
    uv run python backend/tests/manual/provider_connection_check.py nvidia

    # Windows PowerShell:
    $env:VERCEL_API_KEY = "vck_..."; uv run python backend/tests/manual/provider_connection_check.py vercel
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / '.env')
except ImportError:
    pass


@dataclass(frozen=True)
class _ProviderSpec:
    env_vars: tuple[str, ...]
    model: str
    base_url: str | None = None
    provider: str | None = None
    extra_body: dict[str, object] | None = None
    async_client: bool = False


_PROVIDERS: dict[str, _ProviderSpec] = {
    'vercel': _ProviderSpec(
        env_vars=('LLM_API_KEY', 'VERCEL_API_KEY'),
        model='vercel/anthropic/claude-haiku-4.5',
        provider='vercel',
        async_client=True,
    ),
    'nvidia': _ProviderSpec(
        env_vars=('NVIDIA_API_KEY',),
        model='moonshotai/kimi-k2.5',
        base_url='https://integrate.api.nvidia.com/v1',
        extra_body={'chat_template_kwargs': {'thinking': False}},
    ),
}


def _resolve_api_key(spec: _ProviderSpec) -> str:
    for env_var in spec.env_vars:
        value = (os.environ.get(env_var) or '').strip()
        if value:
            return value
    keys = ' or '.join(spec.env_vars)
    print(f'No API key found. Set one of: {keys}')
    return ''


def _send_sync(spec: _ProviderSpec, api_key: str) -> int:
    from backend.inference.direct_clients import get_direct_client

    client = get_direct_client(
        spec.model,
        api_key=api_key,
        base_url=spec.base_url,
        provider=spec.provider,
    )
    print(
        f'Client: {type(client).__name__}, '
        f'model_name={getattr(client, "model_name", "?")}'
    )
    response = client.completion(
        messages=[{'role': 'user', 'content': 'Reply with exactly: ok'}],
        max_tokens=32,
        extra_body=spec.extra_body,
    )
    text = (
        (response.choices[0].message.content or '').strip() if response.choices else ''
    )
    print(f'Response ({len(text)} chars): {text!r}')
    return 0 if text else 1


async def _send_async(spec: _ProviderSpec, api_key: str) -> int:
    from backend.inference.direct_clients import get_direct_client

    client = get_direct_client(
        spec.model,
        api_key=api_key,
        base_url=spec.base_url,
        provider=spec.provider,
        timeout=30.0,
    )
    print(
        f'Client: {type(client).__name__}, '
        f'model_name={getattr(client, "model_name", "?")}'
    )
    response = await client.acompletion(
        messages=[{'role': 'user', 'content': 'Reply with exactly: ok'}],
        model=spec.model,
        max_tokens=10,
        temperature=0,
    )
    text = (
        (response.choices[0].message.content or '').strip() if response.choices else ''
    )
    print(f'Response ({len(text)} chars): {text!r}')
    return 0 if text else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'provider',
        choices=sorted(_PROVIDERS),
        help='Provider to test',
    )
    args = parser.parse_args(argv)
    spec = _PROVIDERS[args.provider]
    api_key = _resolve_api_key(spec)
    if not api_key:
        return 1

    print(f'Testing provider={args.provider!r}, model={spec.model!r}')
    try:
        if spec.async_client:
            return asyncio.run(_send_async(spec, api_key))
        return _send_sync(spec, api_key)
    except Exception as exc:
        print(f'Request failed: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
