"""Configuration management — onboarding, settings I/O, API key handling."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from backend.core.config import load_app_config, AppConfig

_console = Console()

# ---------------------------------------------------------------------------
# Settings file location
# ---------------------------------------------------------------------------

def _settings_path() -> Path:
    """Resolve the canonical settings.json path using the same logic as the backend."""
    root = os.environ.get("APP_ROOT", os.getcwd())
    return Path(root) / "settings.json"


def _load_raw_settings() -> dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_raw_settings(data: dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Onboarding — first-run API key collection
# ---------------------------------------------------------------------------

def needs_onboarding(config: AppConfig) -> bool:
    """Return True when no usable LLM API key is configured."""
    try:
        llm_cfg = config.get_llm_config()
        key = llm_cfg.api_key
        if key is None:
            return True
        raw = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key)
        return not raw or raw.strip() == ""
    except Exception:
        logger.debug("Could not read LLM config for onboarding check", exc_info=True)
        return True


def run_onboarding() -> AppConfig:
    """Interactive first-run: collect API key (and optionally model), persist, return config."""
    _console.print()
    _console.print(
        Panel(
            Text.from_markup(
                "[bold cyan]Welcome to Grinta[/bold cyan]\n\n"
                "No API key detected.  Enter your LLM provider key to get started.\n"
                "Supported providers: OpenAI, Anthropic, Google, DeepSeek, OpenRouter, and more.\n\n"
                "[dim]Your key is stored locally in settings.json — never sent anywhere else.[/dim]"
            ),
            title="[bold]First-Run Setup[/bold]",
            border_style="bright_cyan",
            padding=(1, 4),
        ),
        justify="center",
    )
    _console.print()

    api_key = Prompt.ask("[bold]API Key[/bold]", console=_console)
    model = Prompt.ask(
        "[bold]Model[/bold] [dim](e.g. anthropic/claude-sonnet-4-20250514, openai/gpt-4.1)[/dim]",
        default="",
        console=_console,
    )

    settings = _load_raw_settings()
    settings["llm_api_key"] = api_key.strip()
    if model.strip():
        settings["llm_model"] = model.strip()
    _save_raw_settings(settings)

    _console.print(
        Panel("[green]Configuration saved.[/green]", border_style="green"),
        justify="center",
    )
    _console.print()

    return load_app_config()


# ---------------------------------------------------------------------------
# Programmatic helpers for settings TUI
# ---------------------------------------------------------------------------

def get_current_model(config: AppConfig) -> str:
    try:
        return config.get_llm_config().model or "(not set)"
    except Exception:
        logger.debug("Could not read current model from config", exc_info=True)
        return "(not set)"


def _resolve_api_key_value(config: AppConfig) -> str | None:
    llm_cfg = config.get_llm_config()
    api_key: Any = getattr(llm_cfg, "api_key", None)
    if api_key is not None:
        try:
            raw = api_key.get_secret_value()
        except AttributeError:
            raw = str(api_key)
        raw = raw.strip()
        if raw:
            return raw

    model = (getattr(llm_cfg, "model", "") or "").strip()
    if model:
        try:
            from backend.core.config.api_key_manager import api_key_manager

            provider = api_key_manager.extract_provider(model)
            env_key = api_key_manager.get_provider_key_from_env(provider)
            if env_key and env_key.strip():
                return env_key.strip()
        except Exception:
            logger.debug("Could not resolve env-backed API key", exc_info=True)

    fallback = (os.environ.get("LLM_API_KEY") or "").strip()
    return fallback or None


def _mask_secret(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return "(not set)"
    if len(raw) <= 4:
        return "•" * len(raw)
    if len(raw) <= 8:
        visible = 2
        return raw[:visible] + "•" * (len(raw) - (visible * 2)) + raw[-visible:]
    return raw[:4] + "•" * min(len(raw) - 8, 20) + raw[-4:]


def get_masked_api_key(config: AppConfig) -> str:
    try:
        raw = _resolve_api_key_value(config)
        if not raw:
            return "(not set)"
        return _mask_secret(raw)
    except Exception:
        logger.debug("Could not read API key for masking", exc_info=True)
        return "(not set)"


def update_model(model: str) -> None:
    settings = _load_raw_settings()
    settings["llm_model"] = model
    _save_raw_settings(settings)


def update_api_key(key: str) -> None:
    settings = _load_raw_settings()
    settings["llm_api_key"] = key
    _save_raw_settings(settings)


def get_mcp_servers(config: AppConfig) -> list[dict[str, Any]]:
    try:
        if config.mcp and config.mcp.servers:
            return [
                {
                    "name": s.name,
                    "type": s.type,
                    "url": getattr(s, "url", None),
                    "command": getattr(s, "command", None),
                }
                for s in config.mcp.servers
            ]
    except Exception:
        logger.debug("Could not read MCP server list", exc_info=True)
    return []


def add_mcp_server(name: str, *, url: str | None = None, command: str | None = None) -> None:
    settings = _load_raw_settings()
    mcp_cfg = settings.get("mcp_config", {})
    servers = mcp_cfg.get("servers", [])

    entry: dict[str, Any] = {"name": name}
    if url:
        entry["type"] = "sse"
        entry["url"] = url
    elif command:
        import shlex

        parts = shlex.split(command)
        entry["type"] = "stdio"
        entry["command"] = parts[0]
        entry["args"] = parts[1:]
    else:
        raise ValueError("Specify either url or command")

    servers.append(entry)
    mcp_cfg["servers"] = servers
    settings["mcp_config"] = mcp_cfg
    _save_raw_settings(settings)
