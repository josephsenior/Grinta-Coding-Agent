"""Settings — JSON file I/O."""

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

from backend.cli.settings.constants import *  # noqa: F403

def _settings_path() -> Path:
    """Resolve canonical settings path anchored to repository root."""
    return Path(get_app_settings_root()) / 'settings.json'


def _load_raw_settings() -> dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return {}
    with path.open('r', encoding='utf-8') as f:
        settings = json.load(f)
    legacy_reasoning = settings.pop('reasoningEffort', None)
    if legacy_reasoning is not None and 'llm_reasoning_effort' not in settings:
        settings['llm_reasoning_effort'] = legacy_reasoning
    return settings


def _save_raw_settings(data: dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write('\n')
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
