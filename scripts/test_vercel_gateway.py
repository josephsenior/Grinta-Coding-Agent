"""One-off script to verify Vercel AI Gateway responds.

Run from repo root with LLM_API_KEY or VERCEL_API_KEY set (or in .env):

    python scripts/test_vercel_gateway.py
"""

from __future__ import annotations

import asyncio
import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def _run() -> int:
    api_key = (
        os.environ.get('LLM_API_KEY') or os.environ.get('VERCEL_API_KEY') or ''
    ).strip()
    if not api_key:
        print('LLM_API_KEY or VERCEL_API_KEY is not set.')
        return 1

    from backend.inference.direct_clients import get_direct_client

    model = 'vercel/anthropic/claude-haiku-4.5'
    print(f'Resolving client for model={model!r} ...')
    client = get_direct_client(model, api_key=api_key, provider='vercel', timeout=30.0)
    print(
        f'Client: {type(client).__name__}, '
        f'model_name={getattr(client, "model_name", "?")}'
    )

    print('Sending completion request ...')
    try:
        response = await client.acompletion(
            messages=[{'role': 'user', 'content': 'Reply with exactly: ok'}],
            model=model,
            max_tokens=10,
            temperature=0,
        )
    except Exception as exc:
        print(f'Request failed: {exc}')
        return 1

    text = (
        (response.choices[0].message.content or '').strip() if response.choices else ''
    )
    print(f'Response ({len(text)} chars): {text!r}')
    if not text:
        print('No content in response.')
        return 1
    print('Vercel AI Gateway responded successfully.')
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == '__main__':
    sys.exit(main())
