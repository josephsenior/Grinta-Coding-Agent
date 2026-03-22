"""Environment variable loading for Forge configuration.

Extracted from ``config/utils.py`` to keep the main config orchestrator lean.
Contains the recursive env-var application logic and type casting.
"""

from __future__ import annotations

import os
from ast import literal_eval
from types import NoneType, UnionType
from typing import Any, get_args, get_origin

from pydantic import BaseModel, SecretStr

from backend.core import logger
from backend.core.config.forge_config import ForgeConfig
from backend.core.config.llm_config import LLMConfig

if __name__ != "__main__":
    from collections.abc import MutableMapping


# ---------------------------------------------------------------------------
# Type casting helpers
# ---------------------------------------------------------------------------


def _get_optional_type(union_type: UnionType | type | None) -> type | None:
    """Return the non-None type from a union."""
    if union_type is None:
        return None
    if get_origin(union_type) is UnionType:
        types = get_args(union_type)
        return next((t for t in types if t is not NoneType), None)
    return union_type if isinstance(union_type, type) else None


def _is_dict_or_list_type(field_type: Any) -> bool:
    origin = get_origin(field_type)
    return origin is dict or origin is list or field_type is dict or field_type is list


def _process_list_items(cast_value: list, field_type: Any) -> list:
    args = get_args(field_type)
    if not args:
        return cast_value
    inner_type = args[0]
    if isinstance(inner_type, type) and issubclass(inner_type, BaseModel):
        return [
            inner_type(**item) if isinstance(item, dict) else item
            for item in cast_value
        ]
    return cast_value


def cast_value_to_type(value: str, field_type: Any) -> Any:
    """Cast string value to appropriate type."""
    if get_origin(field_type) is UnionType:
        field_type = _get_optional_type(field_type)

    if field_type is bool:
        return value.lower() in {"true", "1"}

    if _is_dict_or_list_type(field_type):
        cast_value = literal_eval(value)
        if get_origin(field_type) is list:
            cast_value = _process_list_items(cast_value, field_type)
        return cast_value

    if isinstance(field_type, type) and issubclass(field_type, SecretStr):
        return SecretStr(value)

    return field_type(value) if field_type is not None else value


# ---------------------------------------------------------------------------
# Recursive env-var application
# ---------------------------------------------------------------------------


def _process_field_value(
    sub_config: BaseModel,
    field_name: str,
    field_type: Any,
    env_var_name: str,
    env_dict: dict,
) -> None:
    """Process and set field value from environment variable."""
    value = env_dict[env_var_name]
    if not value:
        return

    try:
        if field_name.lower().endswith("api_key"):
            cast_value = SecretStr(value)
        else:
            cast_value = cast_value_to_type(value, field_type)
        setattr(sub_config, field_name, cast_value)

        if field_name == "api_key":
            try:
                from backend.core.config.api_key_manager import api_key_manager

                if hasattr(sub_config, "model") and cast_value is not None:
                    api_key_manager.set_api_key(sub_config.model, cast_value)
                    api_key_manager.set_environment_variables(
                        sub_config.model, cast_value
                    )
            except Exception:
                logger.forge_logger.debug("Failed to sync API key manager")
    except (ValueError, TypeError):
        logger.forge_logger.error(
            "Error setting env var %s=<redacted>: check that the value is of the right type",
            env_var_name,
        )


def _set_attr_from_env(
    sub_config: BaseModel,
    env_dict: dict,
    prefix: str = "",
) -> None:
    """Set attributes of a config model based on environment variables."""
    for field_name, field_info in sub_config.__class__.model_fields.items():
        field_value = getattr(sub_config, field_name)
        field_type = field_info.annotation
        env_var_name = (prefix + field_name).upper()

        if isinstance(field_value, BaseModel):
            _set_attr_from_env(field_value, env_dict, prefix=f"{field_name}_")
        elif env_var_name in env_dict:
            _process_field_value(
                sub_config, field_name, field_type, env_var_name, env_dict
            )


def load_from_env(
    cfg: ForgeConfig, env_or_toml_dict: dict | MutableMapping[str, str]
) -> None:
    """Set config attributes from environment variables or TOML dictionary."""
    env_dict = dict(env_or_toml_dict)

    _set_attr_from_env(cfg, env_dict)
    default_llm_config = cfg.get_llm_config()
    _set_attr_from_env(default_llm_config, env_dict, "LLM_")

    if "LLM_API_KEY" in env_dict:
        from backend.core.config.llm_config import suppress_llm_env_export

        updated_data = default_llm_config.model_dump()
        if isinstance(default_llm_config.api_key, SecretStr):
            updated_data["api_key"] = default_llm_config.api_key.get_secret_value()

        updated_data["api_key"] = env_dict["LLM_API_KEY"]
        with suppress_llm_env_export():
            new_config = LLMConfig.model_validate(updated_data)
        cfg.set_llm_config(new_config)
    else:
        cfg.set_llm_config(default_llm_config)
    _set_attr_from_env(cfg.get_agent_config(), env_dict, "AGENT_")


def restore_environment(original_env: dict[str, str]) -> None:
    """Restore environment variables to their original state after config load side-effects."""
    current_keys = set(os.environ.keys())
    original_keys = set(original_env.keys())

    for added_key in current_keys - original_keys:
        os.environ.pop(added_key, None)

    for key in original_keys:
        os.environ[key] = original_env[key]


def export_llm_api_keys(cfg: ForgeConfig) -> None:
    """Export LLM API keys to environment after all overrides are applied."""
    try:
        from backend.core.config.api_key_manager import api_key_manager

        for llm in cfg.llms.values():
            if llm.api_key and llm.model and str(llm.model).strip():
                api_key_manager.set_api_key(llm.model, llm.api_key)
                api_key_manager.set_environment_variables(llm.model, llm.api_key)
    except Exception:
        logger.forge_logger.debug(
            "Failed to export LLM API keys after configuration load"
        )
