"""Provider defaults and registry."""

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

DEFAULT_ONBOARDING_MODEL = 'openai/gpt-5.1'
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
