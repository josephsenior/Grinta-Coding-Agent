"""Provider defaults and registry."""

from __future__ import annotations

import logging

from rich.console import Console

from backend.cli.theme import (
    no_color_enabled,
)

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
