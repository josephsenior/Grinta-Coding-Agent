"""Split config_manager.py into backend/cli/settings/ submodules."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'cli' / 'config_manager.py'
TARGET = ROOT / 'cli' / 'settings'

SHARED_HEADER = '''"""Settings and onboarding helpers."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from backend.cli.theme import (
    CLR_BRAND,
    CLR_CARD_BORDER,
    CLR_META,
    CLR_SPINNER,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
    CLR_STATUS_WARN,
    no_color_enabled,
)
from backend.core.app_paths import get_app_settings_root
from backend.core.config import AppConfig, load_app_config
from backend.core.config.dotenv_keys import (
    persist_llm_api_key_to_dotenv,
    persist_provider_api_key_to_dotenv,
)
from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER

logger = logging.getLogger(__name__)
_console = Console(no_color=no_color_enabled())
'''

CONSTANTS_BODY = """DEFAULT_ONBOARDING_MODEL = 'openai/gpt-5.1'
DEFAULT_MODEL_BY_PROVIDER: dict[str, str] = {
    'anthropic': 'anthropic/claude-sonnet-4.6',
    'google': 'google/gemini-3-flash',
    'groq': 'groq/meta-llama/llama-4-scout',
    'lightning': 'lightning/meta-llama/Meta-Llama-3.1-8B-Instruct',
    'opencode': 'opencode/deepseek-v4-flash-free',
    'opencode-go': 'opencode-go/glm-5',
    'openai': DEFAULT_ONBOARDING_MODEL,
    'openrouter': 'openrouter/anthropic/claude-4.5-sonnet',
    'vercel': 'vercel/anthropic/claude-haiku-4.5',
    'xai': 'xai/grok-build-0.1',
    'deepseek': 'deepseek/deepseek-v4-flash',
}

# Provider registry — grouped for clean onboarding display.
# (key, display_label, category)
_PROVIDERS: list[tuple[str, str, str]] = [
    ('openai', 'OpenAI', 'cloud'),
    ('anthropic', 'Anthropic', 'cloud'),
    ('google', 'Google Gemini', 'cloud'),
    ('groq', 'Groq', 'cloud'),
    ('xai', 'xAI (Grok)', 'cloud'),
    ('deepseek', 'DeepSeek', 'cloud'),
    ('openrouter', 'OpenRouter', 'aggregator'),
    ('vercel', 'Vercel AI Gateway', 'aggregator'),
    ('lightning', 'Lightning AI', 'aggregator'),
    ('opencode', 'OpenCode Zen', 'aggregator'),
    ('opencode-go', 'OpenCode Go', 'aggregator'),
    ('nvidia', 'NVIDIA NIM', 'aggregator'),
    ('ollama', 'Ollama', 'local'),
    ('lm_studio', 'LM Studio', 'local'),
]
"""

# 1-based inclusive line ranges from config_manager.py
RANGES: dict[str, list[tuple[int, int]]] = {
    'storage': [(79, 112)],
    'onboarding': [(120, 182), (202, 676)],
    'query': [(183, 201), (684, 882)],
    'mcp': [(884, 945)],
}


def _slice(lines: list[str], start: int, end: int) -> list[str]:
    return lines[start - 1 : end]


def _body(lines: list[str], ranges: list[tuple[int, int]]) -> str:
    parts: list[str] = []
    for start, end in ranges:
        parts.extend(_slice(lines, start, end))
    return '\n'.join(parts) + '\n'


def main() -> None:
    lines = SOURCE.read_text(encoding='utf-8').splitlines()

    (TARGET / 'constants.py').write_text(
        SHARED_HEADER + '\n' + CONSTANTS_BODY,
        encoding='utf-8',
    )

    module_imports = {
        'storage': 'from backend.cli.settings.constants import *  # noqa: F403\n',
        'onboarding': (
            'from backend.cli.settings.constants import *  # noqa: F403\n'
            'from backend.cli.settings.storage import (\n'
            '    _load_raw_settings,\n'
            '    _save_raw_settings,\n'
            '    _settings_path,\n'
            ')\n'
        ),
        'query': (
            'from backend.cli.settings.constants import *  # noqa: F403\n'
            'from backend.cli.settings.storage import (\n'
            '    _load_raw_settings,\n'
            '    _save_raw_settings,\n'
            '    _settings_path,\n'
            ')\n'
        ),
        'mcp': (
            'from backend.cli.settings.storage import _load_raw_settings, _save_raw_settings\n'
        ),
    }

    for name, ranges in RANGES.items():
        content = (
            f'"""Settings — {name}."""\n\n'
            + SHARED_HEADER
            + '\n'
            + module_imports[name]
            + '\n'
            + _body(lines, ranges)
        )
        (TARGET / f'{name}.py').write_text(content, encoding='utf-8')

    init = '''"""App settings I/O, onboarding, and programmatic updates."""

from backend.cli.settings.constants import (
    DEFAULT_MODEL_BY_PROVIDER,
    DEFAULT_ONBOARDING_MODEL,
    _PROVIDERS,
)
from backend.cli.settings.mcp import add_mcp_server, get_mcp_servers, remove_mcp_server
from backend.cli.settings.onboarding import (
    auto_detect_api_keys,
    needs_onboarding,
    run_onboarding,
)
from backend.cli.settings.query import (
    ensure_default_model,
    get_budget,
    get_cli_tool_icons_enabled,
    get_current_model,
    get_current_provider,
    get_masked_api_key,
    get_persisted_reasoning_effort,
    update_api_key,
    update_budget,
    update_cli_tool_icons,
    update_model,
    update_reasoning_effort,
)
from backend.cli.settings.storage import (
    _load_raw_settings,
    _save_raw_settings,
    _settings_path,
)

# Test hook
from backend.cli.settings.onboarding import _test_llm_call  # noqa: F401

__all__ = [
    'DEFAULT_MODEL_BY_PROVIDER',
    'DEFAULT_ONBOARDING_MODEL',
    '_PROVIDERS',
    '_load_raw_settings',
    '_save_raw_settings',
    '_settings_path',
    '_test_llm_call',
    'add_mcp_server',
    'auto_detect_api_keys',
    'ensure_default_model',
    'get_budget',
    'get_cli_tool_icons_enabled',
    'get_current_model',
    'get_current_provider',
    'get_masked_api_key',
    'get_mcp_servers',
    'get_persisted_reasoning_effort',
    'needs_onboarding',
    'remove_mcp_server',
    'run_onboarding',
    'update_api_key',
    'update_budget',
    'update_cli_tool_icons',
    'update_model',
    'update_reasoning_effort',
]
'''
    existing_init = TARGET / '__init__.py'
    if existing_init.exists():
        doc = existing_init.read_text(encoding='utf-8').split('\n')[0]
        if doc.startswith('"""'):
            init = doc + '\n\n' + init.split('\n', 2)[2] if False else init

    (TARGET / '__init__.py').write_text(init, encoding='utf-8')
    SOURCE.unlink()
    print('split config_manager -> settings/')


def _rewrite_config_imports() -> None:
    repo = ROOT.parent
    for path in repo.rglob('*'):
        if path.suffix != '.py':
            continue
        text = path.read_text(encoding='utf-8')
        new = text.replace('backend.cli.settings', 'backend.cli.settings')
        if new != text:
            path.write_text(new, encoding='utf-8')


if __name__ == '__main__':
    main()
    _rewrite_config_imports()
