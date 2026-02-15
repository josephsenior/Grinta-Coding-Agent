"""Shared helper functions for loading and working with Forge config files.

Major subsystems have been extracted into focused modules:
- ``env_loader``    – environment variable loading and type casting
- ``model_rebuild`` – Pydantic model forward-reference resolution
- ``cli_config``    – CLI argument parsing and config overrides
- ``config_sections`` – per-section TOML processors

This module remains the primary entry point for ``load_FORGE_config()``
and ``setup_config_from_args()``.
"""

from __future__ import annotations

import os
import pathlib
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

import toml
from pydantic import SecretStr, ValidationError

from backend.core import logger
from backend.core.config.agent_config import AgentConfig
from backend.core.config.cli_config import (
    apply_additional_overrides,
    apply_llm_config_override,
    get_llm_config_arg,
    _load_toml_config,
)
from backend.core.config.config_sections import (
    check_unknown_sections,
    process_agent_section,
    process_condenser_section,
    process_core_section,
    process_extended_section,
    process_llm_section,
    process_mcp_section,
    process_runtime_section,
    process_security_section,
)

from backend.core.config.env_loader import export_llm_api_keys
from backend.core.config.env_loader import (
    load_from_env,
)
from backend.core.config.env_loader import restore_environment
from backend.core.config.forge_config import ForgeConfig
from backend.core.config.model_rebuild import rebuild_config_models
from backend.core.constants import JWT_SECRET_FILE as JWT_SECRET
from backend.storage import get_file_store
from backend.utils.import_utils import get_impl

if TYPE_CHECKING:
    import argparse

    from backend.core.config.condenser_config import CondenserConfig
    from backend.storage.files import FileStore


# ---------------------------------------------------------------------------
# Config load summary
# ---------------------------------------------------------------------------


@dataclass
class _ConfigIssue:
    section: str
    reason: str
    detail: str


class ConfigLoadSummary:
    """Aggregate warnings encountered while loading configuration sections."""

    def __init__(self, toml_file: str) -> None:
        self._toml_file = toml_file
        self._issues: list[_ConfigIssue] = []

    def record(self, section: str, reason: str, detail: str) -> None:
        detail_str = (detail or "").strip()
        if len(detail_str) > 240:
            detail_str = f"{detail_str[:237]}..."
        self._issues.append(
            _ConfigIssue(section=section, reason=reason, detail=detail_str)
        )

    def has_fatal_issues(self) -> bool:
        return any(issue.reason in {"invalid", "error"} for issue in self._issues)

    def format_fatal_issues(self) -> str:
        fatal = [i for i in self._issues if i.reason in {"invalid", "error"}]
        if not fatal:
            return ""
        parts = [f"{i.section}: {i.reason}: {i.detail}" for i in fatal]
        return "; ".join(parts)

    def record_missing(self, section: str, detail: str) -> None:
        self.record(section, "missing", detail)

    def emit(self) -> None:
        if not self._issues:
            return
        grouped: dict[str, list[_ConfigIssue]] = {}
        for issue in self._issues:
            grouped.setdefault(issue.section, []).append(issue)
        lines: list[str] = []
        for section in sorted(grouped.keys()):
            reasons = "; ".join(
                f"{issue.reason}: {issue.detail}" if issue.detail else issue.reason
                for issue in grouped[section]
            )
            lines.append(f"[{section}] {reasons}")
        logger.FORGE_logger.warning(
            "Configuration sections skipped or partially applied while loading %s:\n%s",
            self._toml_file,
            "\n".join(lines),
        )


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _to_posix_workspace_path(path: str) -> str:
    """Convert an OS-specific absolute path to a POSIX-style path."""
    if not path:
        return path
    p = path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        p = p[2:]
    if not p.startswith("/"):
        p = f"/{p}"
    while "//" in p:
        p = p.replace("//", "/")
    return p.rstrip("/") if p != "/" else p


# ---------------------------------------------------------------------------
# Config load
# ---------------------------------------------------------------------------


def load_from_toml(cfg: ForgeConfig, toml_file: str = "config.toml") -> None:
    """Load the config from the toml file."""
    strict_config = os.getenv("FORGE_STRICT_CONFIG", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    summary = ConfigLoadSummary(toml_file)
    try:
        try:
            with open(toml_file, encoding="utf-8") as toml_contents:
                toml_config = toml.load(toml_contents)
        except FileNotFoundError:
            return
        except toml.TomlDecodeError as e:
            logger.FORGE_logger.warning(
                "Cannot parse config from toml, toml values have not been applied.\nError: %s",
                e,
            )
            if strict_config:
                raise ValueError(f"Invalid TOML in {toml_file}") from e
            return
        if "core" not in toml_config:
            logger.FORGE_logger.warning(
                "No [core] section found in %s. Core settings will use defaults.",
                toml_file,
            )
            summary.record_missing("core", "section missing; defaults applied")
            core_config = {}
        else:
            core_config = toml_config["core"]

        process_core_section(core_config, cfg, summary)
        process_agent_section(toml_config, cfg, summary)
        process_llm_section(toml_config, cfg, summary)
        process_security_section(toml_config, cfg, summary)
        process_runtime_section(toml_config, cfg, summary)
        process_mcp_section(toml_config, cfg, summary)
        process_condenser_section(toml_config, cfg, summary)
        process_extended_section(toml_config, cfg, summary)
        check_unknown_sections(toml_config, toml_file)
    finally:
        summary.emit()

    if strict_config and summary.has_fatal_issues():
        raise ValueError(
            f"Strict config mode enabled (FORGE_STRICT_CONFIG=true): config load issues in {toml_file}: "
            f"{summary.format_fatal_issues()}"
        )


# ---------------------------------------------------------------------------
# JWT secret
# ---------------------------------------------------------------------------


def get_or_create_jwt_secret(file_store: FileStore) -> str:
    try:
        return file_store.read(JWT_SECRET)
    except FileNotFoundError:
        new_secret = uuid4().hex
        file_store.write(JWT_SECRET, new_secret)
        return new_secret


# ---------------------------------------------------------------------------
# Finalization
# ---------------------------------------------------------------------------


def finalize_config(cfg: ForgeConfig) -> None:
    """More tweaks to the config after it's been loaded."""
    _configure_llm_logging(cfg)
    _ensure_cache_directory(cfg)
    _configure_jwt_secret(cfg)


def _configure_llm_logging(cfg: ForgeConfig) -> None:
    for llm in cfg.llms.values():
        llm.log_completions_folder = os.path.abspath(llm.log_completions_folder)


def _ensure_cache_directory(cfg: ForgeConfig) -> None:
    if cfg.cache_dir:
        pathlib.Path(cfg.cache_dir).mkdir(parents=True, exist_ok=True)


def _configure_jwt_secret(cfg: ForgeConfig) -> None:
    if not cfg.jwt_secret:
        cfg.jwt_secret = SecretStr(
            get_or_create_jwt_secret(
                get_file_store(cfg.file_store, cfg.file_store_path)
            )
        )


# ---------------------------------------------------------------------------
# Named config group loaders (agent, llm, condenser)
# ---------------------------------------------------------------------------


def get_agent_config_arg(
    agent_config_arg: str, toml_file: str = "config.toml"
) -> AgentConfig | None:
    """Get a group of agent settings from the config file."""
    agent_config_arg = agent_config_arg.strip("[]").removeprefix("agent.")
    logger.FORGE_logger.debug("Loading agent config from %s", agent_config_arg)
    toml_config = _load_toml_config(toml_file)
    if toml_config is None:
        return None
    if "agent" in toml_config and agent_config_arg in toml_config["agent"]:
        return AgentConfig(**toml_config["agent"][agent_config_arg])
    logger.FORGE_logger.debug("Loading from toml failed for %s", agent_config_arg)
    return None


# ---------------------------------------------------------------------------
# Condenser config group loader
# ---------------------------------------------------------------------------


def _validate_condenser_section(
    toml_config: dict, condenser_config_arg: str, toml_file: str
) -> dict | None:
    if (
        "condenser" not in toml_config
        or condenser_config_arg not in toml_config["condenser"]
    ):
        logger.FORGE_logger.error(
            "Condenser config section [condenser.%s] not found in %s",
            condenser_config_arg,
            toml_file,
        )
        return None
    return toml_config["condenser"][condenser_config_arg].copy()


def _process_llm_condenser(
    condenser_data: dict, condenser_config_arg: str, toml_file: str
) -> dict | None:
    llm_config_name = condenser_data["llm_config"]
    logger.FORGE_logger.debug(
        "Condenser [%s] requires LLM config [%s]. Loading it...",
        condenser_config_arg,
        llm_config_name,
    )
    if referenced_llm_config := get_llm_config_arg(
        llm_config_name, toml_file=toml_file
    ):
        condenser_data["llm_config"] = referenced_llm_config
        return condenser_data
    logger.FORGE_logger.error(
        "Failed to load required LLM config '%s' for condenser '%s'.",
        llm_config_name,
        condenser_config_arg,
    )
    return None


def _process_condenser_data(
    condenser_data: dict, condenser_config_arg: str, toml_file: str
) -> dict | None:
    condenser_type = condenser_data.get("type")
    if (
        condenser_type in ("llm", "llm_attention", "structured")
        and "llm_config" in condenser_data
        and isinstance(condenser_data["llm_config"], str)
    ):
        return _process_llm_condenser(condenser_data, condenser_config_arg, toml_file)
    return condenser_data


def get_condenser_config_arg(
    condenser_config_arg: str, toml_file: str = "config.toml"
) -> CondenserConfig | None:
    """Get a group of condenser settings from the config file by name."""
    condenser_config_arg = condenser_config_arg.strip("[]").removeprefix("condenser.")
    logger.FORGE_logger.debug(
        "Loading condenser config [%s] from %s", condenser_config_arg, toml_file
    )

    toml_config = _load_toml_config(toml_file)
    if toml_config is None:
        return None

    condenser_data = _validate_condenser_section(
        toml_config, condenser_config_arg, toml_file
    )
    if condenser_data is None:
        return None

    condenser_type = condenser_data.get("type")
    if not condenser_type:
        logger.FORGE_logger.error(
            'Missing "type" field in [condenser.%s] section of %s',
            condenser_config_arg,
            toml_file,
        )
        return None

    condenser_data = _process_condenser_data(
        condenser_data, condenser_config_arg, toml_file
    )
    if condenser_data is None:
        return None

    try:
        from backend.core.config.condenser_config import create_condenser_config

        config = create_condenser_config(condenser_type, condenser_data)
        logger.FORGE_logger.info(
            "Successfully loaded condenser config [%s] from %s",
            condenser_config_arg,
            toml_file,
        )
        return config
    except (ValidationError, ValueError) as e:
        logger.FORGE_logger.error(
            "Invalid condenser configuration for [%s]: %s.", condenser_config_arg, e
        )
        return None


# ---------------------------------------------------------------------------
# Agent registration
# ---------------------------------------------------------------------------


def register_custom_agents(config: ForgeConfig) -> None:
    """Register custom agents from configuration."""
    from backend.controller.agent import Agent

    for agent_name, agent_config in config.agents.items():
        classpath = getattr(agent_config, "classpath", None)
        if classpath:
            try:
                agent_cls = get_impl(Agent, classpath)
                Agent.register(agent_name, agent_cls)
                logger.FORGE_logger.info(
                    "Registered custom agent '%s' from %s", agent_name, classpath
                )
            except Exception as e:
                logger.FORGE_logger.error(
                    "Failed to register agent '%s': %s", agent_name, e
                )


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    from backend.core.config.arg_utils import get_headless_parser

    parser = get_headless_parser()
    args = parser.parse_args()
    if args.version:
        sys.exit(0)
    return args


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def load_FORGE_config(
    set_logging_levels: bool = True, config_file: str = "config.toml"
) -> ForgeConfig:
    """Load the configuration from the specified config file and environment variables."""
    rebuild_config_models()

    original_env = dict(os.environ)

    config = ForgeConfig()
    load_from_toml(config, config_file)
    restore_environment(original_env)
    env_copy = dict(os.environ)
    env_copy.pop("LLM_API_KEY", None)
    load_from_env(config, env_copy)
    finalize_config(config)
    export_llm_api_keys(config)
    register_custom_agents(config)
    if set_logging_levels:
        logger.DEBUG = config.debug
        logger.DISABLE_COLOR_PRINTING = config.disable_color
    return config


def setup_config_from_args(args: argparse.Namespace) -> ForgeConfig:
    """Load config from toml and override with command line arguments.

    Configuration precedence (from highest to lowest):
    1. CLI parameters (e.g., -l for LLM config)
    2. config.toml in current directory (or --config-file location if specified)
    3. ~/.Forge/settings.json and ~/.Forge/config.toml
    """
    config = load_FORGE_config(config_file=args.config_file)
    apply_llm_config_override(config, args)
    apply_additional_overrides(config, args)
    return config
