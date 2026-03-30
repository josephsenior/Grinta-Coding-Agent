"""CLI configuration resolution.

Extracted from ``config/utils.py`` to keep the main config orchestrator lean.
Contains argument parsing and config-override logic for CLI entry points.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import json

from backend.core import logger
from backend.core.app_paths import get_app_settings_root
from backend.core.config.app_config import AppConfig
from backend.core.config.llm_config import LLMConfig

if TYPE_CHECKING:
    import argparse


def _load_json_config(json_file: str) -> dict | None:
    """Load and parse JSON configuration file."""
    try:
        with open(json_file, "r", encoding="utf-8") as json_contents:
            return json.load(json_contents)
    except FileNotFoundError as e:
        logger.app_logger.error("Config file not found: %s. Error: %s", json_file, e)
        return None
    except Exception as e:
        logger.app_logger.error(
            "Cannot parse config file %s. Exception: %s", json_file, e
        )
        return None


def get_llm_config_arg(
    llm_config_arg: str, json_file: str = "settings.json"
) -> LLMConfig | None:
    """Get llm settings from the config file."""
    json_config = _load_json_config(json_file)
    if json_config is None:
        return None

    # Check if there are any LLM keys present
    llm_keys = ("llm_model", "llm_api_key", "llm_base_url")
    if not any(k in json_config for k in llm_keys):
        return None

    llm = LLMConfig()
    if "llm_model" in json_config:
        llm.model = json_config["llm_model"]
    if "llm_api_key" in json_config:
        llm.api_key = json_config["llm_api_key"]
    if "llm_base_url" in json_config:
        llm.base_url = json_config["llm_base_url"]
    return llm


def _resolve_llm_config_from_cli(
    llm_config_name: str, config: AppConfig, config_file: str
) -> LLMConfig:
    """Resolve LLM config from CLI parameter."""
    if llm_config_name in config.llms:
        logger.app_logger.debug(
            "Using LLM config '%s' from loaded configuration", llm_config_name
        )
        return config.llms[llm_config_name]

    llm_config = get_llm_config_arg(llm_config_name, config_file)
    if llm_config is None:
        llm_config = _try_user_config_llm(llm_config_name, config_file)

    if llm_config is None:
        msg = f"Cannot find LLM configuration '{llm_config_name}' in any config file"
        raise ValueError(msg)

    return llm_config


def _try_user_config_llm(llm_config_name: str, config_file: str) -> LLMConfig | None:
    """Try LLM keys from canonical ``settings.json`` if the primary file had no LLM block."""
    canonical = os.path.join(get_app_settings_root(), "settings.json")
    canonical_abs = os.path.abspath(os.path.normpath(canonical))
    primary_abs = os.path.abspath(os.path.normpath(config_file))
    if primary_abs == canonical_abs or not os.path.isfile(canonical_abs):
        return None

    logger.app_logger.debug(
        "Trying to load LLM config '%s' from canonical settings: %s",
        llm_config_name,
        canonical_abs,
    )
    return get_llm_config_arg(llm_config_name, canonical_abs)


def apply_llm_config_override(config: AppConfig, args: argparse.Namespace) -> None:
    """Apply LLM config override from CLI arguments."""
    if not args.llm_config:
        return

    logger.app_logger.debug("CLI specified LLM config: %s", args.llm_config)
    llm_config = _resolve_llm_config_from_cli(args.llm_config, config, args.config_file)
    config.set_llm_config(llm_config)
    logger.app_logger.debug("Set LLM config from CLI parameter: %s", args.llm_config)


def apply_additional_overrides(config: AppConfig, args: argparse.Namespace) -> None:
    """Apply additional config overrides from CLI arguments."""
    if hasattr(args, "agent_cls") and args.agent_cls:
        config.default_agent = args.agent_cls
    if hasattr(args, "max_iterations") and args.max_iterations is not None:
        config.max_iterations = args.max_iterations
    if hasattr(args, "max_budget_per_task") and args.max_budget_per_task is not None:
        config.max_budget_per_task = args.max_budget_per_task
