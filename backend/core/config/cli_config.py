"""CLI configuration resolution.

Extracted from ``config/utils.py`` to keep the main config orchestrator lean.
Contains argument parsing and config-override logic for CLI entry points.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import toml

from backend.core import logger
from backend.core.config.forge_config import ForgeConfig
from backend.core.config.llm_config import LLMConfig

if TYPE_CHECKING:
    import argparse


def _load_toml_config(toml_file: str) -> dict | None:
    """Load and parse TOML configuration file."""
    try:
        with open(toml_file, encoding="utf-8") as toml_contents:
            return toml.load(toml_contents)
    except FileNotFoundError as e:
        logger.FORGE_logger.error("Config file not found: %s. Error: %s", toml_file, e)
        return None
    except toml.TomlDecodeError as e:
        logger.FORGE_logger.error(
            "Cannot parse config file %s. Exception: %s", toml_file, e
        )
        return None


def get_llm_config_arg(
    llm_config_arg: str, toml_file: str = "config.toml"
) -> LLMConfig | None:
    """Get a group of llm settings from the config file."""
    llm_config_arg = llm_config_arg.strip("[]").removeprefix("llm.")
    logger.FORGE_logger.debug(
        'Loading llm config "%s" from %s', llm_config_arg, toml_file
    )
    toml_config = _load_toml_config(toml_file)
    if toml_config is None:
        return None
    if "llm" in toml_config and llm_config_arg in toml_config["llm"]:
        return LLMConfig(**toml_config["llm"][llm_config_arg])
    logger.FORGE_logger.debug(
        'LLM config "%s" not found in %s', llm_config_arg, toml_file
    )
    return None


def _resolve_llm_config_from_cli(
    llm_config_name: str, config: ForgeConfig, config_file: str
) -> LLMConfig:
    """Resolve LLM config from CLI parameter."""
    if llm_config_name in config.llms:
        logger.FORGE_logger.debug(
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
    """Try to load LLM config from user config file."""
    user_config = os.path.join(os.path.expanduser("~"), ".Forge", "config.toml")
    if config_file == user_config or not os.path.exists(user_config):
        return None

    logger.FORGE_logger.debug(
        "Trying to load LLM config '%s' from user config: %s",
        llm_config_name,
        user_config,
    )
    return get_llm_config_arg(llm_config_name, user_config)


def apply_llm_config_override(config: ForgeConfig, args: argparse.Namespace) -> None:
    """Apply LLM config override from CLI arguments."""
    if not args.llm_config:
        return

    logger.FORGE_logger.debug("CLI specified LLM config: %s", args.llm_config)
    llm_config = _resolve_llm_config_from_cli(args.llm_config, config, args.config_file)
    config.set_llm_config(llm_config)
    logger.FORGE_logger.debug("Set LLM config from CLI parameter: %s", args.llm_config)


def apply_additional_overrides(config: ForgeConfig, args: argparse.Namespace) -> None:
    """Apply additional config overrides from CLI arguments."""
    if hasattr(args, "agent_cls") and args.agent_cls:
        config.default_agent = args.agent_cls
    if hasattr(args, "max_iterations") and args.max_iterations is not None:
        config.max_iterations = args.max_iterations
    if hasattr(args, "max_budget_per_task") and args.max_budget_per_task is not None:
        config.max_budget_per_task = args.max_budget_per_task
