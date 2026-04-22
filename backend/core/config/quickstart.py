"""Quick-start configuration generator for new App users.

Generates a minimal ``settings.json`` with only the settings that matter
on day one.  Every other knob inherits sensible defaults.

Usage (CLI)::

    python -m backend.core.config.quickstart

Usage (programmatic)::

    from backend.core.config.quickstart import generate_quickstart_config
    json_str = generate_quickstart_config(model="gemini-2.5-flash")
    # Put the real key in repo-root .env as LLM_API_KEY=...

"""

from __future__ import annotations

import json
import os
from pathlib import Path

from backend.core.config.dotenv_keys import persist_llm_api_key_to_dotenv
from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER
from backend.inference.provider_resolver import discover_all_local_models


def generate_quickstart_config(
    *,
    model: str = 'gemini-2.5-flash',
    base_url: str = '',
    max_budget: float = 5.0,
) -> str:
    """Return a minimal quick-start ``settings.json`` as a string.

    The LLM secret is not embedded: ``llm_api_key`` is the placeholder
    ``${LLM_API_KEY}``; set ``LLM_API_KEY`` in repo-root ``.env``.

    Args:
        model: Default model identifier.
        base_url: Optional base URL for the LLM endpoint.
        max_budget: Maximum spend per task in USD.

    Returns:
        A JSON-formatted configuration string.
    """
    config = {
        'project_root': './workspace',
        'max_budget_per_task': max_budget,
        'llm_model': model,
        'llm_api_key': LLM_API_KEY_SETTINGS_PLACEHOLDER,
        'llm_base_url': base_url or '',
    }
    return json.dumps(config, indent=2)


def _interactive_init(dest: Path) -> None:
    """Walk the user through creating a minimal config file."""
    print('\n🚀 App Quick-Start Configuration')
    print('=' * 60)

    # 1. Detect local models
    print('\n🔍 Scanning for local LLMs (Ollama, LM Studio, etc.)...')
    local_models = discover_all_local_models()
    suggested_model = 'gemini-2.5-flash'

    found_any = False
    for provider, models in local_models.items():
        if models:
            if not found_any:
                print('   ✨ Found local models!')
                found_any = True
            print(f'   📦 {provider}: {", ".join(models[:3])}...')
            # Suggest the first local model as a default if nothing else is picked
            suggested_model = f'{provider}/{models[0]}'

    print(f'\n💡 Suggestion: {suggested_model}')
    print('-' * 60)

    if dest.exists():
        confirm = (
            input(f'\n⚠️  {dest.name} already exists. Overwrite? [y/N]: ')
            .strip()
            .lower()
        )
        if confirm != 'y':
            print('   Aborted.')
            return

    model = input(f'   Model name [{suggested_model}]: ').strip() or suggested_model
    api_key = ''
    if '/' not in model:
        api_key = input('   LLM API key (optional): ').strip()

    budget_str = input('   Max budget per task (USD) [5.0]: ').strip()
    max_budget = float(budget_str) if budget_str else 5.0

    content = generate_quickstart_config(model=model, max_budget=max_budget)

    dest.write_text(content, encoding='utf-8')
    if api_key.strip():
        persist_llm_api_key_to_dotenv(api_key.strip(), settings_json_path=dest)

    # Ensure workspace exists
    (dest.parent / 'workspace').mkdir(exist_ok=True)

    print(f'\n✅ Configuration saved to {dest}')
    print(f'📁 Workspace initialized at {dest.parent}/workspace/')
    print('\n👉 To start, run: uv run python -m backend.cli.entry\n')


# ------------------------------------------------------------------ #
# CLI entrypoint                                                      #
# ------------------------------------------------------------------ #


def main() -> None:
    """CLI entry-point: ``python -m backend.core.config.quickstart``."""
    # Determine project root (where settings.json lives)
    project_root = Path(os.environ.get('APP_PROJECT_ROOT', Path.cwd()))
    dest = project_root / 'settings.json'
    _interactive_init(dest)


if __name__ == '__main__':
    main()
