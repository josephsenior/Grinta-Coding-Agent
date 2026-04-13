"""One-off script to verify NVIDIA NIM Kimi K2.5 model responds.

Run from repo root with NVIDIA_API_KEY set (or in .env):

    python scripts/test_nvidia_kimi.py

    # Windows PowerShell:
    $env:NVIDIA_API_KEY = "your-key"; python scripts/test_nvidia_kimi.py

    # Linux/macOS:
    NVIDIA_API_KEY=your-key python scripts/test_nvidia_kimi.py
"""
from __future__ import annotations

import os
import sys

# Load .env from project root if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Ensure backend is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    api_key = os.environ.get('NVIDIA_API_KEY', '').strip()
    if not api_key:
        print('NVIDIA_API_KEY is not set. Set it and re-run, e.g.:')
        print('  $env:NVIDIA_API_KEY = "nvapi-..."; python scripts/test_nvidia_kimi.py')
        return 1

    from backend.inference.direct_clients import get_direct_client

    # API expects "moonshotai/kimi-k2.5" (dot) per NVIDIA docs
    model = 'moonshotai/kimi-k2.5'
    base_url = 'https://integrate.api.nvidia.com/v1'
    print(f'Resolving client for model={model!r}, base_url={base_url!r} ...')
    client = get_direct_client(model, api_key=api_key, base_url=base_url)
    print(f"Client: {type(client).__name__}, model_name={getattr(client, 'model_name', '?')}")

    messages = [{'role': 'user', 'content': 'Reply with exactly: Hello from Kimi.'}]
    # Disable reasoning/thinking so the reply is in content (NVIDIA Kimi uses reasoning by default)
    extra = {'chat_template_kwargs': {'thinking': False}}
    print('Sending completion request ...')
    try:
        response = client.completion(messages, max_tokens=64, extra_body=extra)
    except Exception as e:
        print(f'Request failed: {e}')
        return 1

    text = (response.choices[0].message.content or '').strip() if response.choices else ''
    print(f'Response ({len(text)} chars): {text!r}')
    if not text:
        print('No content in response.')
        return 1
    print('Model responded successfully.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
