#!/usr/bin/env python3
"""CLI utility for discovering and managing local LLM models.

Usage:
    python -m backend.inference.discover_models          # Discover all local models
    python -m backend.inference.discover_models status   # Check provider status
"""

from __future__ import annotations

import sys
from typing import TextIO

from backend.core.logger import app_logger as logger
from backend.inference.provider_resolver import (
    check_local_providers,
    discover_all_local_models,
)


def print_section(title: str) -> None:
    """Print a section header."""
    print(f'\n{"=" * 60}')
    print(f'  {title}')
    print('=' * 60)


def _stream_supports(text: str, stream: TextIO | None = None) -> bool:
    """Return True when *stream* can encode *text*."""
    target = stream or sys.stdout
    encoding = getattr(target, 'encoding', None) or 'utf-8'
    try:
        text.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def _icon(symbol: str, fallback: str) -> str:
    """Return a Unicode icon when stdout supports it, otherwise ASCII."""
    if _stream_supports(symbol):
        return symbol
    return fallback


def _display_provider_name(provider: str) -> str:
    """Render provider ids in a user-facing format."""
    return provider.upper().replace('_', ' ')


def _model_reference(provider: str, model: str) -> str:
    """Return the settings-ready model id for a discovered local model."""
    if model.startswith(f'{provider}/'):
        return model
    return f'{provider}/{model}'


def discover_command() -> None:
    """Discover all available local models."""
    print_section('Local Model Discovery')

    print('\nDiscovering local LLM providers...')
    models = discover_all_local_models()

    if not models:
        print(f'{_icon("❌", "[!]")} No local providers found.')
        print('\nTo use local models:')
        print('  1. Start Ollama, LM Studio, or vLLM locally.')
        print('  2. Make sure an API server is listening on the default port:')
        print('     - Ollama: http://localhost:11434')
        print('     - LM Studio: http://localhost:1234')
        print('     - vLLM: http://localhost:8000')
        print('  3. Run this command again.')
        return

    total_models = sum(len(m) for m in models.values())
    print(
        f'\n{_icon("✓", "[OK]")} Found {total_models} models '
        f'across {len(models)} providers:\n'
    )

    for provider, model_list in models.items():
        print(f'{_icon("📦", "[provider]")} {_display_provider_name(provider)}')
        for model in model_list:
            print(f'   - {model}')

    print(f'\n{_icon("💡", "[tip]")} Settings examples:')
    for provider, model_list in models.items():
        if not model_list:
            continue
        sample_model = _model_reference(provider, model_list[0])
        print(f'   {provider}: set llm_model to "{sample_model}"')


def status_command() -> None:
    """Check status of local providers."""
    print_section('Local Provider Status')

    print('\nChecking local LLM providers...\n')
    status = check_local_providers()

    for provider, is_running in status.items():
        status_icon = _icon('✓', '[OK]') if is_running else _icon('✗', '[--]')
        status_text = 'RUNNING' if is_running else 'NOT FOUND'
        provider_name = _display_provider_name(provider)
        print(f'{status_icon} {provider_name:<15} {status_text}')

    if not any(status.values()):
        print(f'\n{_icon("💡", "[tip]")} No local providers are running.')
        print('\nStart Ollama, LM Studio, or vLLM, then run this command again.')


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        command = 'discover'
    else:
        command = sys.argv[1].lower()

    commands = {
        'discover': discover_command,
        'status': status_command,
    }

    if command not in commands:
        print(f'Unknown command: {command}')
        print(f'\nAvailable commands: {", ".join(commands.keys())}')
        return 1

    try:
        commands[command]()
        return 0
    except Exception as e:
        logger.error('Command failed: %s', e, exc_info=True)
        print(f'\n{_icon("❌", "[ERROR]")} Error: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
