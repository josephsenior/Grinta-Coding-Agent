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
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import SecretStr, ValidationError

from backend.core import logger
from backend.core.config.agent_config import AgentConfig
from backend.core.config.cli_config import (
    apply_additional_overrides,
    apply_llm_config_override,
    get_llm_config_arg,
    _load_json_config,
)

from backend.core.config.env_loader import export_llm_api_keys
from backend.core.config.env_loader import (
    load_from_env,
)
from backend.core.config.env_loader import restore_environment
from backend.core.config.forge_config import ForgeConfig
from backend.core.config.llm_config import LLMConfig
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
        logger.forge_logger.warning(
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


from backend.core.config.extended_config import ExtendedConfig  # noqa: E402


def load_from_json(cfg: ForgeConfig, json_file: str = "settings.json") -> None:
    """Load the config from the flat settings.json file."""
    strict_config = os.getenv("FORGE_STRICT_CONFIG", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    summary = ConfigLoadSummary(json_file)
    try:
        try:
            with open(json_file, "r", encoding="utf-8") as json_contents:
                data = json.load(json_contents)
        except FileNotFoundError:
            return
        except Exception as e:
            logger.forge_logger.warning(
                "Cannot parse config from json, json values have not been applied.\nError: %s",
                e,
            )
            if strict_config:
                raise ValueError(f"Invalid JSON in {json_file}") from e
            return

        # Manually map flat data into ForgeConfig
        # Core & Runtime Settings
        if "runtime" in data and data["runtime"]:
            cfg.runtime = data["runtime"]
        if "file_store" in data and data["file_store"]:
            cfg.file_store = data["file_store"]
        if "file_store_path" in data and data["file_store_path"]:
            cfg.file_store_path = data["file_store_path"]
        if "workspace_base" in data and data["workspace_base"]:
            cfg.workspace_base = data["workspace_base"]
        if (
            "workspace_mount_path_in_runtime" in data
            and data["workspace_mount_path_in_runtime"]
        ):
            cfg.workspace_mount_path_in_runtime = data[
                "workspace_mount_path_in_runtime"
            ]
        if "enable_browser" in data and data["enable_browser"] is not None:
            cfg.enable_browser = data["enable_browser"]
        if "cache_dir" in data and data["cache_dir"]:
            cfg.cache_dir = data["cache_dir"]
        if "max_iterations" in data and data["max_iterations"] is not None:
            cfg.max_iterations = data["max_iterations"]
        if "max_budget_per_task" in data and data["max_budget_per_task"] is not None:
            cfg.max_budget_per_task = data["max_budget_per_task"]
        if (
            "max_budget_per_session" in data
            and data["max_budget_per_session"] is not None
        ):
            cfg.max_budget_per_session = data["max_budget_per_session"]
        if "max_budget_per_day" in data and data["max_budget_per_day"] is not None:
            cfg.max_budget_per_day = data["max_budget_per_day"]
        if "debug" in data and data["debug"] is not None:
            cfg.debug = data["debug"]
        if "disable_color" in data and data["disable_color"] is not None:
            cfg.disable_color = data["disable_color"]
        if (
            "conversation_max_age_seconds" in data
            and data["conversation_max_age_seconds"] is not None
        ):
            cfg.conversation_max_age_seconds = data["conversation_max_age_seconds"]
        if (
            "max_concurrent_conversations" in data
            and data["max_concurrent_conversations"] is not None
        ):
            cfg.max_concurrent_conversations = data["max_concurrent_conversations"]
        if "vcs_user_name" in data and data["vcs_user_name"]:
            cfg.vcs_user_name = data["vcs_user_name"]
        if "vcs_user_email" in data and data["vcs_user_email"]:
            cfg.vcs_user_email = data["vcs_user_email"]
        if "log_format" in data and data["log_format"]:
            cfg.log_format = data["log_format"]
        if "log_level" in data and data["log_level"]:
            cfg.log_level = data["log_level"]
        if "mcp_host" in data and data["mcp_host"]:
            cfg.mcp_host = data["mcp_host"]
        if (
            "init_git_in_empty_workspace" in data
            and data["init_git_in_empty_workspace"] is not None
        ):
            cfg.init_git_in_empty_workspace = data["init_git_in_empty_workspace"]
        if "run_as_Forge" in data and data["run_as_Forge"] is not None:
            cfg.run_as_Forge = data["run_as_Forge"]

        # Trajectory
        if "save_trajectory_path" in data and data["save_trajectory_path"]:
            cfg.trajectory.save_path = data["save_trajectory_path"]
        if "replay_trajectory_path" in data and data["replay_trajectory_path"]:
            cfg.trajectory.replay_path = data["replay_trajectory_path"]
        if (
            "save_screenshots_in_trajectory" in data
            and data["save_screenshots_in_trajectory"] is not None
        ):
            cfg.trajectory.save_screenshots = data["save_screenshots_in_trajectory"]

        # File Uploads
        if (
            "file_uploads_max_file_size_mb" in data
            and data["file_uploads_max_file_size_mb"] is not None
        ):
            cfg.file_uploads.max_file_size_mb = data["file_uploads_max_file_size_mb"]
        if (
            "file_uploads_restrict_file_types" in data
            and data["file_uploads_restrict_file_types"] is not None
        ):
            cfg.file_uploads.restrict_file_types = data[
                "file_uploads_restrict_file_types"
            ]
        if (
            "file_uploads_allowed_extensions" in data
            and data["file_uploads_allowed_extensions"]
        ):
            cfg.file_uploads.allowed_extensions = set(
                data["file_uploads_allowed_extensions"]
            )

        # Security
        if "confirmation_mode" in data and data["confirmation_mode"] is not None:
            cfg.security.confirmation_mode = data["confirmation_mode"]
        if "security_analyzer" in data and data["security_analyzer"]:
            cfg.security.security_analyzer = data["security_analyzer"]

        # LLM — build from data without creating an empty LLMConfig() first,
        # so we never trigger "No API key found" during load when the key is in JSON.
        llm_keys = ("llm_model", "llm_api_key", "llm_base_url", "llm_temperature")
        if any(k in data for k in llm_keys) or "llm_model" in data:
            from backend.core.constants import DEFAULT_LLM_MODEL

            base = cfg.llms.get("llm")
            llm_dict = (
                base.model_dump(exclude_none=True)
                if base
                else {"model": DEFAULT_LLM_MODEL}
            )
            if "llm_model" in data and data["llm_model"]:
                llm_dict["model"] = data["llm_model"]
            if "llm_api_key" in data and data["llm_api_key"]:
                llm_dict["api_key"] = data["llm_api_key"]
            if "llm_base_url" in data and data["llm_base_url"]:
                llm_dict["base_url"] = data["llm_base_url"]
            if "llm_temperature" in data and data["llm_temperature"] is not None:
                llm_dict["temperature"] = data["llm_temperature"]
            if "llm_top_p" in data and data["llm_top_p"] is not None:
                llm_dict["top_p"] = data["llm_top_p"]
            if (
                "llm_max_output_tokens" in data
                and data["llm_max_output_tokens"] is not None
            ):
                llm_dict["max_output_tokens"] = data["llm_max_output_tokens"]
            if "llm_timeout" in data and data["llm_timeout"] is not None:
                llm_dict["timeout"] = data["llm_timeout"]
            if "llm_num_retries" in data and data["llm_num_retries"] is not None:
                llm_dict["num_retries"] = data["llm_num_retries"]
            if (
                "llm_custom_llm_provider" in data
                and data["llm_custom_llm_provider"] is not None
            ):
                llm_dict["custom_llm_provider"] = data["llm_custom_llm_provider"]
            if (
                "llm_caching_prompt" in data
                and data["llm_caching_prompt"] is not None
            ):
                llm_dict["caching_prompt"] = data["llm_caching_prompt"]
            if (
                "llm_disable_vision" in data
                and data["llm_disable_vision"] is not None
            ):
                llm_dict["disable_vision"] = data["llm_disable_vision"]
            cfg.set_llm_config(LLMConfig.model_validate(llm_dict))

        # Default Agent config
        agent_name = data.get("agent") or "Orchestrator"
        cfg.default_agent = agent_name

        agent_config = cfg.get_agent_config(agent_name)
        if (
            "agent_enable_browsing" in data
            and data["agent_enable_browsing"] is not None
        ):
            agent_config.enable_browsing = data["agent_enable_browsing"]
        if "agent_enable_cmd" in data and data["agent_enable_cmd"] is not None:
            agent_config.enable_cmd = data["agent_enable_cmd"]
        if "agent_enable_think" in data and data["agent_enable_think"] is not None:
            agent_config.enable_think = data["agent_enable_think"]
        if "agent_enable_finish" in data and data["agent_enable_finish"] is not None:
            agent_config.enable_finish = data["agent_enable_finish"]
        if (
            "agent_enable_circuit_breaker" in data
            and data["agent_enable_circuit_breaker"] is not None
        ):
            agent_config.enable_circuit_breaker = data["agent_enable_circuit_breaker"]
        if (
            "agent_enable_graceful_shutdown" in data
            and data["agent_enable_graceful_shutdown"] is not None
        ):
            agent_config.enable_graceful_shutdown = data[
                "agent_enable_graceful_shutdown"
            ]
        if (
            "agent_enable_history_truncation" in data
            and data["agent_enable_history_truncation"] is not None
        ):
            agent_config.enable_history_truncation = data[
                "agent_enable_history_truncation"
            ]
        if (
            "agent_enable_condensation_request" in data
            and data["agent_enable_condensation_request"] is not None
        ):
            agent_config.enable_condensation_request = data[
                "agent_enable_condensation_request"
            ]
        if (
            "enable_task_tracker" in data
            and data["enable_task_tracker"] is not None
        ):
            agent_config.enable_internal_task_tracker = data["enable_task_tracker"]

        # Graph RAG
        if "graph_rag_enabled" in data and data["graph_rag_enabled"]:
            cfg.extended = cfg.extended or ExtendedConfig.from_dict({})
            try:
                # Assuming GraphRAGConfig was accessible, but if we don't know the exact class just set logic:
                ext_dict = (
                    dict(cfg.extended.model_dump())
                    if hasattr(cfg.extended, "model_dump")
                    else {}
                )
                gr_data = {"enabled": True}
                if (
                    "graph_rag_persistence_path" in data
                    and data["graph_rag_persistence_path"]
                ):
                    gr_data["persistence_path"] = data["graph_rag_persistence_path"]
                if (
                    "graph_rag_graph_depth" in data
                    and data["graph_rag_graph_depth"] is not None
                ):
                    gr_data["graph_depth"] = data["graph_rag_graph_depth"]
                if (
                    "graph_rag_max_seed_results" in data
                    and data["graph_rag_max_seed_results"] is not None
                ):
                    gr_data["max_seed_results"] = data["graph_rag_max_seed_results"]
                ext_dict["graph_rag"] = gr_data
                cfg.extended = ExtendedConfig.from_dict(ext_dict)
            except Exception:
                pass

        # MCP
        from backend.core.config.mcp_config import (
            MCPConfig,
            _filter_windows_stdio_servers,
            _load_servers_from_config_json,
        )

        if "mcp_config" in data and data["mcp_config"] is not None:
            cfg.mcp = MCPConfig(**data["mcp_config"])

        # Always attempt to load servers from backend/runtime/mcp/config.json
        # (same as the TOML path does via from_toml_section).  This covers the
        # common case where mcp_config is null in settings.json but the user
        # has a config.json with mcpServers entries.
        cfg.mcp.servers = _load_servers_from_config_json(list(cfg.mcp.servers))
        cfg.mcp.servers = _filter_windows_stdio_servers(cfg.mcp.servers)

    finally:
        summary.emit()

    if strict_config and summary.has_fatal_issues():
        raise ValueError(
            f"Strict config mode enabled (FORGE_STRICT_CONFIG=true): config load issues in {json_file}: "
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
    agent_config_arg: str, json_file: str = "settings.json"
) -> AgentConfig | None:
    """Get a group of agent settings from the config file."""
    agent_config_arg = agent_config_arg.strip("[]").removeprefix("agent.")
    logger.forge_logger.debug("Loading agent config from %s", agent_config_arg)
    json_config = _load_json_config(json_file)
    if json_config is None:
        return None
    if "agent" in json_config and agent_config_arg in json_config["agent"]:
        return AgentConfig(**json_config["agent"][agent_config_arg])
    logger.forge_logger.debug("Loading from toml failed for %s", agent_config_arg)
    return None


# ---------------------------------------------------------------------------
# Condenser config group loader
# ---------------------------------------------------------------------------


def _validate_condenser_section(
    json_config: dict, condenser_config_arg: str, json_file: str
) -> dict | None:
    if "condenser_type" not in json_config:
        logger.forge_logger.error(
            "Condenser config section [condenser.%s] not found in %s",
            condenser_config_arg,
            json_file,
        )
        return None

    condenser_dict = {"type": json_config.get("condenser_type")}
    if json_config.get("condenser_max_events") is not None:
        condenser_dict["max_events"] = json_config.get("condenser_max_events")
    if json_config.get("condenser_keep_first") is not None:
        condenser_dict["keep_first"] = json_config.get("condenser_keep_first")
    if json_config.get("condenser_llm_config") is not None:
        condenser_dict["llm_config"] = json_config.get("condenser_llm_config")

    return condenser_dict


def _process_llm_condenser(
    condenser_data: dict, condenser_config_arg: str, json_file: str
) -> dict | None:
    llm_config_name = condenser_data.get("llm_config")
    if not llm_config_name:
        return None

    logger.forge_logger.debug(
        "Condenser [%s] requires LLM config [%s]. Loading it...",
        condenser_config_arg,
        llm_config_name,
    )
    if referenced_llm_config := get_llm_config_arg(
        llm_config_name, json_file=json_file
    ):
        condenser_data["llm_config"] = referenced_llm_config
        return condenser_data
    logger.forge_logger.error(
        "Failed to load required LLM config '%s' for condenser '%s'.",
        llm_config_name,
        condenser_config_arg,
    )
    return None


def _process_condenser_data(
    condenser_data: dict, condenser_config_arg: str, json_file: str
) -> dict | None:
    condenser_type = condenser_data.get("type")
    if (
        condenser_type in ("llm", "llm_attention", "structured")
        and "llm_config" in condenser_data
        and isinstance(condenser_data["llm_config"], str)
    ):
        return _process_llm_condenser(condenser_data, condenser_config_arg, json_file)
    return condenser_data


def get_condenser_config_arg(
    condenser_config_arg: str, json_file: str = "settings.json"
) -> CondenserConfig | None:
    """Get a group of condenser settings from the config file by name."""
    condenser_config_arg = condenser_config_arg.strip("[]").removeprefix("condenser.")
    logger.forge_logger.debug(
        "Loading condenser config [%s] from %s", condenser_config_arg, json_file
    )

    json_config = _load_json_config(json_file)
    if json_config is None:
        return None

    condenser_data = _validate_condenser_section(
        json_config, condenser_config_arg, json_file
    )
    if condenser_data is None:
        return None

    condenser_type = condenser_data.get("type")
    if not condenser_type:
        logger.forge_logger.error(
            'Missing "type" field in [condenser.%s] section of %s',
            condenser_config_arg,
            json_file,
        )
        return None

    condenser_data = _process_condenser_data(
        condenser_data, condenser_config_arg, json_file
    )
    if condenser_data is None:
        return None

    try:
        from backend.core.config.condenser_config import create_condenser_config

        config = create_condenser_config(condenser_type, condenser_data)
        logger.forge_logger.info(
            "Successfully loaded condenser config [%s] from %s",
            condenser_config_arg,
            json_file,
        )
        return config
    except (ValidationError, ValueError) as e:
        logger.forge_logger.error(
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
                logger.forge_logger.info(
                    "Registered custom agent '%s' from %s", agent_name, classpath
                )
            except Exception as e:
                logger.forge_logger.error(
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


def load_forge_config(
    set_logging_levels: bool = True, config_file: str = "settings.json"
) -> ForgeConfig:
    """Load the configuration from environment variables and the specified config file.

    Precedence (highest to lowest):
    1. settings.json (explicit user configuration)
    2. Environment variables (deployment-specific overrides)
    3. Defaults (hardcoded fallbacks)
    """
    rebuild_config_models()

    config = ForgeConfig()

    # 1. Load from environment first (lower precedence than file)
    load_from_env(config, dict(os.environ))

    # 2. Load from JSON (higher precedence, overrides env vars)
    # CRITICAL: Use suppress_env_export_context to prevent LLMConfig from
    # logging "No API key found" before we've had a chance to sync.
    from backend.core.config.api_key_manager import api_key_manager
    with api_key_manager.suppress_env_export_context():
        load_from_json(config, config_file)
        # Ensure the default LLM config is updated with the loaded values
        # and its model_post_init (which triggers key resolution) is re-run
        # but with suppression still active.
        llm_cfg = config.get_llm_config()
        # Re-trigger post_init logic by re-validating
        # Use model_dump(exclude_none=True) to avoid issues with None values
        config.set_llm_config(llm_cfg.__class__.model_validate(llm_cfg.model_dump(exclude_none=True)))

    # 3. Finalize and sync
    finalize_config(config)
    
    # CRITICAL: Sync the loaded config (which might have come from settings.json)
    # back to the APIKeyManager so that DirectLLMClient can find it.
    from backend.core.config.api_key_manager import api_key_manager
    # Temporarily suppress env export to avoid double-setting during sync
    with api_key_manager.suppress_env_export_context():
        for llm_name, llm_cfg in config.llms.items():
            if llm_cfg.api_key:
                api_key_manager.set_api_key(llm_cfg.model, llm_cfg.api_key)
                api_key_manager.set_environment_variables(llm_cfg.model, llm_cfg.api_key)
            else:
                # If no key in config, try to load from environment
                provider = api_key_manager._extract_provider(llm_cfg.model)
                env_key = api_key_manager._get_provider_key_from_env(provider)
                if env_key:
                    from pydantic import SecretStr
                    llm_cfg.api_key = SecretStr(env_key)
                    api_key_manager.set_api_key(llm_cfg.model, llm_cfg.api_key)
                    api_key_manager.set_environment_variables(llm_cfg.model, llm_cfg.api_key)
    
    # Export all keys to environment after sync
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
    2. settings.json in current directory (or --config-file location if specified)
    3. ~/.Forge/settings.json
    """
    config = load_forge_config(config_file=args.config_file)
    apply_llm_config_override(config, args)
    apply_additional_overrides(config, args)
    return config
