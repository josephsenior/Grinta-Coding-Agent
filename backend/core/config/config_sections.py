"""TOML section processors for Forge configuration loading.

Extracted from config/utils.py to reduce its size. Contains the per-section
processing functions (_process_core_section, _process_agent_section, etc.)
and the load_from_toml orchestrator.
"""

from __future__ import annotations

from types import UnionType
from typing import TYPE_CHECKING, get_args, get_origin, get_type_hints

from pydantic import SecretStr, ValidationError

from backend.core.config.agent_config import AgentConfig
from backend.core.config.extended_config import ExtendedConfig
from backend.core.config.forge_config import ForgeConfig
from backend.core.config.llm_config import LLMConfig
from backend.core.config.mcp_config import MCPConfig
from backend.core.config.runtime_config import RuntimeConfig
from backend.core.config.security_config import SecurityConfig
from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.core.config.utils import ConfigLoadSummary


def process_core_section(
    core_config: dict, cfg: ForgeConfig, summary: ConfigLoadSummary | None = None
) -> None:
    """Process the [core] section of the TOML config."""
    try:
        cfg_type_hints = get_type_hints(cfg.__class__)
    except NameError:
        cfg_type_hints = getattr(cfg.__class__, "__annotations__", {})
    for key, value in core_config.items():
        if hasattr(cfg, key):
            if expected_type := cfg_type_hints.get(key, None):
                origin = get_origin(expected_type)
                args = get_args(expected_type)
                if (
                    origin is UnionType and SecretStr in args and isinstance(value, str)
                ) or (expected_type is SecretStr and isinstance(value, str)):
                    value = SecretStr(value)
            setattr(cfg, key, value)
        else:
            logger.warning('Unknown config key "%s" in [core] section', key)


def process_agent_section(
    toml_config: dict, cfg: ForgeConfig, summary: ConfigLoadSummary | None = None
) -> None:
    """Process the [agent] section of the TOML config."""
    if "agent" in toml_config:
        try:
            agent_mapping = AgentConfig.from_toml_section(toml_config["agent"])
            for agent_key, agent_conf in agent_mapping.items():
                cfg.set_agent_config(agent_conf, agent_key)
        except (TypeError, KeyError, ValidationError) as e:
            logger.warning(
                "Cannot parse [agent] config from toml, values have not been applied.\nError: %s",
                e,
            )
            if summary:
                summary.record("agent", "invalid", str(e))


def process_llm_section(
    toml_config: dict, cfg: ForgeConfig, summary: ConfigLoadSummary | None = None
) -> None:
    """Process the [llm] section of the TOML config."""
    if "llm" in toml_config:
        from backend.core.config.llm_config import suppress_llm_env_export

        try:
            with suppress_llm_env_export():
                llm_instance = LLMConfig()
                llm_mapping = llm_instance.from_toml_section(toml_config["llm"])

            base_llm = llm_mapping.pop("llm", None)
            for llm_key, llm_conf in llm_mapping.items():
                cfg.set_llm_config(llm_conf, llm_key)
            if base_llm is not None:
                cfg.set_llm_config(base_llm, "llm")
        except (TypeError, KeyError, ValidationError) as e:
            logger.warning(
                "Cannot parse [llm] config from toml, values have not been applied.\nError: %s",
                e,
            )
            if summary:
                summary.record("llm", "invalid", str(e))


def process_security_section(
    toml_config: dict, cfg: ForgeConfig, summary: ConfigLoadSummary | None = None
) -> None:
    """Process the [security] section of the TOML config."""
    if "security" in toml_config:
        try:
            security_mapping = SecurityConfig.from_toml_section(toml_config["security"])
            if "security" in security_mapping:
                cfg.security = security_mapping["security"]
        except (TypeError, KeyError, ValidationError) as e:
            logger.warning(
                "Cannot parse [security] config from toml, values have not been applied.\nError: %s",
                e,
            )
            if summary:
                summary.record("security", "invalid", str(e))
        except ValueError as exc:
            if summary:
                summary.record("security", "warning", str(exc))
            logger.warning(
                "Cannot parse [security] config from toml, values have not been applied.\nError: %s",
                exc,
            )


def process_runtime_section(
    toml_config: dict, cfg: ForgeConfig, summary: ConfigLoadSummary | None = None
) -> None:
    """Process the [runtime] section of the TOML config."""
    if "runtime" in toml_config:
        try:
            runtime_mapping = RuntimeConfig.from_toml_section(toml_config["runtime"])
            if "runtime_config" in runtime_mapping:
                cfg.runtime_config = runtime_mapping["runtime_config"]
        except (TypeError, KeyError, ValidationError) as e:
            logger.warning(
                "Cannot parse [runtime] config from toml, values have not been applied.\nError: %s",
                e,
            )
            if summary:
                summary.record("runtime", "invalid", str(e))
        except ValueError as e:
            if summary:
                summary.record("runtime", "error", str(e))
            msg = "Error in [runtime] section in settings.json"
            raise ValueError(msg) from e


def process_mcp_section(
    toml_config: dict, cfg: ForgeConfig, summary: ConfigLoadSummary | None = None
) -> None:
    """Process the [mcp] section of the TOML config."""
    if "mcp" in toml_config:
        try:
            mcp_mapping = MCPConfig.from_toml_section(toml_config["mcp"])
            if "mcp" in mcp_mapping:
                cfg.mcp = mcp_mapping["mcp"]
        except (TypeError, KeyError, ValidationError) as e:
            logger.warning(
                "Cannot parse MCP config from toml, values have not been applied.\nError: %s",
                e,
            )
            if summary:
                summary.record("mcp", "invalid", str(e))
        except ValueError as err:
            if summary:
                summary.record("mcp", "error", str(err))
            msg = "Error in MCP sections in settings.json"
            raise ValueError(msg) from err


def process_condenser_section(
    toml_config: dict, cfg: ForgeConfig, summary: ConfigLoadSummary | None = None
) -> None:
    """Process the [condenser] section of the TOML config."""
    if "condenser" in toml_config:
        try:
            from backend.core.config.condenser_config import (
                condenser_config_from_toml_section,
            )

            condenser_mapping = condenser_config_from_toml_section(
                toml_config["condenser"], cfg.llms
            )
            if "condenser" in condenser_mapping:
                default_agent_config = cfg.get_agent_config()
                default_agent_config.condenser_config = condenser_mapping["condenser"]
                logger.debug(
                    "Default condenser configuration loaded from config toml and assigned to default agent",
                )
        except (TypeError, KeyError, ValidationError) as e:
            logger.warning(
                "Cannot parse [condenser] config from toml, values have not been applied.\nError: %s",
                e,
            )
            if summary:
                summary.record("condenser", "invalid", str(e))
    elif cfg.enable_default_condenser:
        from backend.core.config.condenser_config import LLMSummarizingCondenserConfig

        default_agent_config = cfg.get_agent_config()
        default_condenser = LLMSummarizingCondenserConfig(
            llm_config=cfg.get_llm_config(), type="llm"
        )
        default_agent_config.condenser_config = default_condenser
        logger.debug(
            "Default LLM summarizing condenser assigned to default agent (no condenser in config)",
        )


def process_extended_section(
    toml_config: dict, cfg: ForgeConfig, summary: ConfigLoadSummary | None = None
) -> None:
    """Process the [extended] section of the TOML config."""
    if "extended" in toml_config:
        try:
            cfg.extended = ExtendedConfig(toml_config["extended"])
        except (TypeError, KeyError, ValidationError) as e:
            logger.warning(
                "Cannot parse [extended] config from toml, values have not been applied.\nError: %s",
                e,
            )
            if summary:
                summary.record("extended", "invalid", str(e))


def check_unknown_sections(toml_config: dict, toml_file: str) -> None:
    """Check for unknown sections in the TOML config."""
    known_sections = {
        "core",
        "extended",
        "agent",
        "llm",
        "security",
        "runtime",
        "condenser",
        "mcp",
        "model_aliases",
        "api_keys",
    }
    for key in toml_config:
        if key.lower() not in known_sections:
            logger.debug("Unknown section [%s] in %s", key, toml_file)
