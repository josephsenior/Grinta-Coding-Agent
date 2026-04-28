"""Shared helper functions for loading and working with application config files.

Major subsystems have been extracted into focused modules:
- ``env_loader``    – environment variable loading and type casting
- ``model_rebuild`` – Pydantic model forward-reference resolution
- ``cli_config``    – CLI argument parsing and config overrides
- ``config_sections`` – per-section TOML processors

This module remains the primary entry point for ``load_app_config()``
and ``setup_config_from_args()``.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from pydantic import SecretStr, ValidationError

from backend.core import logger
from backend.core.app_paths import get_canonical_settings_path
from backend.core.config.agent_config import AgentConfig
from backend.core.config.app_config import AppConfig
from backend.core.config.cli_config import (
    _load_json_config,
    apply_additional_overrides,
    apply_llm_config_override,
    get_llm_config_arg,
)
from backend.core.config.env_loader import (
    export_llm_api_keys,
    load_from_env,
)
from backend.core.config.llm_config import LLMConfig
from backend.core.config.model_rebuild import rebuild_config_models
from backend.core.constants import JWT_SECRET_FILE as JWT_SECRET
from backend.persistence import get_file_store
from backend.persistence.locations import get_local_data_root
from backend.utils.import_utils import get_impl

if TYPE_CHECKING:
    import argparse

    from backend.core.config.compactor_config import CompactorConfig
    from backend.persistence.files import FileStore


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
        detail_str = (detail or '').strip()
        if len(detail_str) > 240:
            detail_str = f'{detail_str[:237]}...'
        self._issues.append(
            _ConfigIssue(section=section, reason=reason, detail=detail_str)
        )

    def has_fatal_issues(self) -> bool:
        return any(issue.reason in {'invalid', 'error'} for issue in self._issues)

    def format_fatal_issues(self) -> str:
        fatal = [i for i in self._issues if i.reason in {'invalid', 'error'}]
        if not fatal:
            return ''
        parts = [f'{i.section}: {i.reason}: {i.detail}' for i in fatal]
        return '; '.join(parts)

    def record_missing(self, section: str, detail: str) -> None:
        self.record(section, 'missing', detail)

    def emit(self) -> None:
        if not self._issues:
            return
        grouped: dict[str, list[_ConfigIssue]] = {}
        for issue in self._issues:
            grouped.setdefault(issue.section, []).append(issue)
        lines: list[str] = []
        for section in sorted(grouped.keys()):
            reasons = '; '.join(
                f'{issue.reason}: {issue.detail}' if issue.detail else issue.reason
                for issue in grouped[section]
            )
            lines.append(f'[{section}] {reasons}')
        logger.app_logger.warning(
            'Configuration sections skipped or partially applied while loading %s:\n%s',
            self._toml_file,
            '\n'.join(lines),
        )


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _to_posix_workspace_path(path: str) -> str:
    """Convert an OS-specific absolute path to a POSIX-style path."""
    if not path:
        return path
    p = path.replace('\\', '/')
    if len(p) >= 2 and p[1] == ':':
        p = p[2:]
    if not p.startswith('/'):
        p = f'/{p}'
    while '//' in p:
        p = p.replace('//', '/')
    return p.rstrip('/') if p != '/' else p


_JSON_LLM_KEYS = ('llm_model', 'llm_api_key', 'llm_base_url', 'llm_provider')


def _load_json_settings(
    json_file: str, *, strict_config: bool
) -> dict[str, object] | None:
    try:
        with open(json_file, 'r', encoding='utf-8') as json_contents:
            return cast(dict[str, object], json.load(json_contents))
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.app_logger.warning(
            'Cannot parse config from json, json values have not been applied.\nError: %s',
            exc,
        )
        if strict_config:
            raise ValueError(f'Invalid JSON in {json_file}') from exc
        return None


def _json_has_llm_overrides(data: dict[str, object]) -> bool:
    return any(key in data for key in _JSON_LLM_KEYS)


def _apply_json_llm_model(llm_dict: dict[str, object], raw_model: object) -> None:
    if raw_model is not None and str(raw_model).strip():
        llm_dict['model'] = str(raw_model).strip()
        return
    llm_dict['model'] = None


def _warn_on_literal_llm_api_key(raw_secret: object) -> None:
    from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER

    if raw_secret is None:
        return
    secret = str(raw_secret).strip()
    if not secret or secret == LLM_API_KEY_SETTINGS_PLACEHOLDER:
        return
    logger.app_logger.warning(
        'settings.json has a literal llm_api_key; it is ignored. '
        'Set LLM_API_KEY in .env and use "%s" for llm_api_key in settings.json.',
        LLM_API_KEY_SETTINGS_PLACEHOLDER,
    )


def _sync_llm_api_key_from_env(llm_dict: dict[str, object]) -> None:
    env_llm_key = (os.environ.get('LLM_API_KEY') or '').strip()
    if env_llm_key:
        llm_dict['api_key'] = env_llm_key
        return
    llm_dict.pop('api_key', None)


def _should_skip_native_google_base_url(
    llm_dict: dict[str, object], provider: object
) -> bool:
    model_str = str(llm_dict.get('model') or '').lower()
    is_native_google = (
        model_str.startswith('google/') or model_str.startswith('gemini-')
    ) and not provider
    return is_native_google


def _apply_json_llm_base_url(
    llm_dict: dict[str, object], data: dict[str, object]
) -> None:
    raw_base_url = data.get('llm_base_url')
    if not raw_base_url:
        return
    provider = data.get('llm_provider') or llm_dict.get('provider')
    if _should_skip_native_google_base_url(llm_dict, provider):
        return
    llm_dict['base_url'] = str(raw_base_url).strip()


def _canonicalize_json_llm_selection(
    llm_dict: dict[str, object], data: dict[str, object]
) -> tuple[str | None, str | None]:
    from backend.inference.provider_resolver import canonicalize_model_selection

    provider = data.get('llm_provider') or llm_dict.get('provider')
    return canonicalize_model_selection(
        cast(str | None, llm_dict.get('model')),
        str(provider) if provider is not None else None,
    )


def _maybe_set_provider_default_base_url(
    llm_dict: dict[str, object], model_value: str | None, provider_value: str | None
) -> None:
    if not provider_value or llm_dict.get('base_url'):
        return

    from backend.inference.provider_resolver import (
        _PROVIDER_DEFAULT_URLS,
        extract_provider_prefix,
    )

    model_prefix = extract_provider_prefix(model_value or '')
    if model_prefix == provider_value:
        return
    provider_url = _PROVIDER_DEFAULT_URLS.get(provider_value)
    if provider_url:
        llm_dict['base_url'] = provider_url


def _handle_missing_json_llm_provider(
    llm_dict: dict[str, object],
    provider_value: str | None,
    *,
    json_file: str,
    strict_config: bool,
) -> bool:
    if not llm_dict.get('model') or provider_value:
        return False
    msg = 'llm_provider is required when llm_model does not include a provider prefix'
    if strict_config:
        raise ValueError(msg)
    logger.app_logger.warning('Skipping LLM config from %s: %s', json_file, msg)
    return True


def _build_json_llm_config(
    cfg: AppConfig, data: dict[str, object]
) -> dict[str, object]:
    base = cfg.llms.get('llm')
    llm_dict = base.model_dump(exclude_none=True) if base else {}
    if 'llm_model' in data:
        _apply_json_llm_model(llm_dict, data['llm_model'])
    _warn_on_literal_llm_api_key(data.get('llm_api_key'))
    _sync_llm_api_key_from_env(llm_dict)
    _apply_json_llm_base_url(llm_dict, data)
    return llm_dict


def _apply_json_llm_config(
    cfg: AppConfig,
    data: dict[str, object],
    *,
    json_file: str,
    strict_config: bool,
) -> None:
    if not _json_has_llm_overrides(data):
        return

    llm_dict = _build_json_llm_config(cfg, data)
    model_value, provider_value = _canonicalize_json_llm_selection(llm_dict, data)
    if model_value:
        llm_dict['model'] = model_value
    _maybe_set_provider_default_base_url(llm_dict, model_value, provider_value)
    if _handle_missing_json_llm_provider(
        llm_dict,
        provider_value,
        json_file=json_file,
        strict_config=strict_config,
    ):
        return
    cfg.set_llm_config(LLMConfig.model_validate(llm_dict))


def _apply_json_top_level_fields(cfg: AppConfig, data: dict[str, object]) -> None:
    if data.get('mcp_host'):
        cfg.mcp_host = cast(str, data['mcp_host'])
    if data.get('project_root'):
        cfg.project_root = cast(str, data['project_root'])


def _parse_mcp_server_entry(entry: object):
    from backend.core.config.mcp_config import MCPServerConfig

    if not isinstance(entry, dict):
        return None
    try:
        return MCPServerConfig(**entry)
    except Exception as exc:
        logger.app_logger.debug('Skipping invalid mcp_config server %r: %s', entry, exc)
        return None


def _apply_json_mcp_servers(cfg: AppConfig, data: dict[str, object]) -> None:
    mcp_config = data.get('mcp_config')
    if not isinstance(mcp_config, dict):
        return

    raw_servers = mcp_config.get('servers') or []
    parsed = [server for entry in raw_servers if (server := _parse_mcp_server_entry(entry))]
    if not parsed:
        return

    existing_names = {server.name for server in cfg.mcp.servers}
    cfg.mcp.servers = list(cfg.mcp.servers) + [
        server for server in parsed if server.name not in existing_names
    ]
    cfg.mcp.enabled = True


def _filter_agent_updates(raw_updates: object) -> dict[str, object] | None:
    if not isinstance(raw_updates, dict):
        return None
    allowed_fields = set(AgentConfig.model_fields)
    filtered = {key: value for key, value in raw_updates.items() if key in allowed_fields}
    if not filtered:
        return None
    return filtered


def _apply_json_agent_override(
    cfg: AppConfig, agent_name: str, filtered: dict[str, object], json_file: str
) -> None:
    try:
        agent_base = cfg.get_agent_config(agent_name)
        merged = {**agent_base.model_dump(), **filtered}
        agent_configs: dict[str, AgentConfig] = cfg.agents
        agent_configs[agent_name] = AgentConfig.model_validate(merged)
    except Exception as exc:
        logger.app_logger.warning(
            'Skipping invalid agent overrides for %r in %s: %s',
            agent_name,
            json_file,
            exc,
        )


def _apply_json_agent_overrides(
    cfg: AppConfig, data: dict[str, object], json_file: str
) -> None:
    agents = data.get('agent')
    if not isinstance(agents, dict):
        return

    for agent_name, raw_updates in agents.items():
        if not isinstance(agent_name, str):
            continue
        filtered = _filter_agent_updates(raw_updates)
        if filtered is None:
            continue
        _apply_json_agent_override(cfg, agent_name, filtered, json_file)


# ---------------------------------------------------------------------------
# Config load
# ---------------------------------------------------------------------------


def load_from_json(cfg: AppConfig, json_file: str = 'settings.json') -> None:
    """Load the config from the flat settings.json file."""
    strict_config = os.getenv('APP_STRICT_CONFIG', 'false').lower() in (
        '1',
        'true',
        'yes',
    )
    summary = ConfigLoadSummary(json_file)
    try:
        data = _load_json_settings(json_file, strict_config=strict_config)
        if data is None:
            return
        _apply_json_llm_config(
            cfg,
            data,
            json_file=json_file,
            strict_config=strict_config,
        )
        _apply_json_top_level_fields(cfg, data)
        _apply_json_mcp_servers(cfg, data)
        _apply_json_agent_overrides(cfg, data, json_file)

    finally:
        summary.emit()

    if strict_config and summary.has_fatal_issues():
        raise ValueError(
            f'Strict config mode enabled (APP_STRICT_CONFIG=true): config load issues in {json_file}: '
            f'{summary.format_fatal_issues()}'
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
# Finalization helpers
# ---------------------------------------------------------------------------


def _get_active_agent_config(cfg: AppConfig) -> AgentConfig:
    agent_name = getattr(cfg, 'default_agent', None) or 'agent'
    return cfg.get_agent_config(agent_name)


def _ensure_active_agent_auto_compactor(cfg: AppConfig) -> None:
    from backend.core.config.compactor_config import AutoCompactorConfig

    agent_config = _get_active_agent_config(cfg)
    compactor_config = getattr(agent_config, 'compactor_config', None)
    if compactor_config is None:
        agent_config.compactor_config = AutoCompactorConfig(
            llm_config=cfg.get_llm_config_from_agent(cfg.default_agent)
        )
        return
    if (
        isinstance(compactor_config, AutoCompactorConfig)
        and compactor_config.llm_config is None
    ):
        agent_config.compactor_config = AutoCompactorConfig(
            llm_config=cfg.get_llm_config_from_agent(cfg.default_agent)
        )


# ---------------------------------------------------------------------------
# Finalization
# ---------------------------------------------------------------------------


def finalize_config(cfg: AppConfig) -> None:
    """More tweaks to the config after it's been loaded."""
    from backend.core.config.mcp_config import extend_mcp_servers_with_bundled_defaults

    _ensure_active_agent_auto_compactor(cfg)
    agent_cfg = cfg.get_agent_config(cfg.default_agent)
    # In-process native browser (browser-use) needs AppConfig.enable_browser on the runtime.
    # Do not clobber agent enable_browsing here — respect loaded defaults / settings.
    cfg.enable_browser = bool(
        agent_cfg.enable_browsing
        and getattr(agent_cfg, 'enable_native_browser', False)
    )
    extend_mcp_servers_with_bundled_defaults(cfg.mcp.servers)
    _configure_llm_logging(cfg)
    _ensure_cache_directory(cfg)
    _configure_jwt_secret(cfg)
    # Persist the effective store root on the config object so reload paths (e.g.
    # /settings) match get_local_data_root() and never leave legacy "." / sessions.
    cfg.local_data_root = get_local_data_root(cfg)


def _configure_llm_logging(cfg: AppConfig) -> None:
    for llm in cfg.llms.values():
        llm.log_completions_folder = os.path.abspath(llm.log_completions_folder)


def _ensure_cache_directory(cfg: AppConfig) -> None:
    if cfg.cache_dir:
        pathlib.Path(cfg.cache_dir).mkdir(parents=True, exist_ok=True)


def _configure_jwt_secret(cfg: AppConfig) -> None:
    if not cfg.jwt_secret:
        cfg.jwt_secret = SecretStr(
            get_or_create_jwt_secret(
                get_file_store(cfg.file_store, get_local_data_root(cfg))
            )
        )


# ---------------------------------------------------------------------------
# Named config group loaders (agent, llm, compactor)
# ---------------------------------------------------------------------------


def get_agent_config_arg(
    agent_config_arg: str, json_file: str = 'settings.json'
) -> AgentConfig | None:
    """Get a group of agent settings from the config file."""
    agent_config_arg = agent_config_arg.strip('[]').removeprefix('agent.')
    logger.app_logger.debug('Loading agent config from %s', agent_config_arg)
    json_config = _load_json_config(json_file)
    if json_config is None:
        return None
    if 'agent' in json_config and agent_config_arg in json_config['agent']:
        return AgentConfig(**json_config['agent'][agent_config_arg])
    logger.app_logger.debug('Loading from toml failed for %s', agent_config_arg)
    return None


# ---------------------------------------------------------------------------
# Compactor config group loader
# ---------------------------------------------------------------------------


def _validate_compactor_section(
    json_config: dict, compactor_config_arg: str, json_file: str
) -> dict | None:
    if 'compactor_type' not in json_config:
        logger.app_logger.error(
            'Compactor config section [compactor.%s] not found in %s',
            compactor_config_arg,
            json_file,
        )
        return None

    compactor_dict = {'type': json_config.get('compactor_type')}
    if json_config.get('compactor_max_events') is not None:
        compactor_dict['max_events'] = json_config.get('compactor_max_events')
    if json_config.get('compactor_keep_first') is not None:
        compactor_dict['keep_first'] = json_config.get('compactor_keep_first')
    if json_config.get('compactor_llm_config') is not None:
        compactor_dict['llm_config'] = json_config.get('compactor_llm_config')

    return compactor_dict


def _process_llm_compactor(
    compactor_data: dict, compactor_config_arg: str, json_file: str
) -> dict | None:
    llm_config_name = compactor_data.get('llm_config')
    if not llm_config_name:
        return None

    logger.app_logger.debug(
        'Compactor [%s] requires LLM config [%s]. Loading it...',
        compactor_config_arg,
        llm_config_name,
    )
    if referenced_llm_config := get_llm_config_arg(
        llm_config_name, json_file=json_file
    ):
        compactor_data['llm_config'] = referenced_llm_config
        return compactor_data
    logger.app_logger.error(
        "Failed to load required LLM config '%s' for compactor '%s'.",
        llm_config_name,
        compactor_config_arg,
    )
    return None


def _process_compactor_data(
    compactor_data: dict, compactor_config_arg: str, json_file: str
) -> dict | None:
    compactor_type = compactor_data.get('type')
    if (
        compactor_type in ('llm', 'llm_attention', 'structured')
        and 'llm_config' in compactor_data
        and isinstance(compactor_data['llm_config'], str)
    ):
        return _process_llm_compactor(compactor_data, compactor_config_arg, json_file)
    return compactor_data


def get_compactor_config_arg(
    compactor_config_arg: str, json_file: str = 'settings.json'
) -> CompactorConfig | None:
    """Get a group of compactor settings from the config file by name."""
    compactor_config_arg = compactor_config_arg.strip('[]').removeprefix('compactor.')
    logger.app_logger.debug(
        'Loading compactor config [%s] from %s', compactor_config_arg, json_file
    )

    json_config = _load_json_config(json_file)
    if json_config is None:
        return None

    compactor_data = _validate_compactor_section(
        json_config, compactor_config_arg, json_file
    )
    if compactor_data is None:
        return None

    compactor_type = compactor_data.get('type')
    if not compactor_type:
        logger.app_logger.error(
            'Missing "type" field in [compactor.%s] section of %s',
            compactor_config_arg,
            json_file,
        )
        return None

    compactor_data = _process_compactor_data(
        compactor_data, compactor_config_arg, json_file
    )
    if compactor_data is None:
        return None

    try:
        from backend.core.config.compactor_config import create_compactor_config

        config = create_compactor_config(compactor_type, compactor_data)
        logger.app_logger.info(
            'Successfully loaded compactor config [%s] from %s',
            compactor_config_arg,
            json_file,
        )
        return config
    except (ValidationError, ValueError) as e:
        logger.app_logger.error(
            'Invalid compactor configuration for [%s]: %s.', compactor_config_arg, e
        )
        return None


# ---------------------------------------------------------------------------
# Agent registration
# ---------------------------------------------------------------------------


def register_custom_agents(config: AppConfig) -> None:
    """Register custom agents from configuration."""
    from backend.orchestration.agent import Agent

    for agent_name, agent_config in config.agents.items():
        classpath = getattr(agent_config, 'classpath', None)
        if classpath:
            try:
                agent_cls = get_impl(Agent, classpath)
                Agent.register(agent_name, agent_cls)
                logger.app_logger.info(
                    "Registered custom agent '%s' from %s", agent_name, classpath
                )
            except Exception as e:
                logger.app_logger.error(
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


def load_app_config(
    set_logging_levels: bool = True, config_file: str = 'settings.json'
) -> AppConfig:
    """Load the configuration from environment variables and the specified config file.

    **LLM API key** comes only from ``LLM_API_KEY`` in the process environment
    (typically set via repo-root ``.env``). In ``settings.json``, ``llm_api_key`` must be
    ``"${LLM_API_KEY}"`` or empty; a literal secret there is ignored with a warning.

    For other fields, settings.json generally overrides environment defaults loaded first;
    see ``load_from_json`` / ``load_from_env`` implementation.
    """
    rebuild_config_models()

    # Hard-enforce a single source of truth for configuration.
    # External config files are ignored by design; only repo-root settings.json is used.
    resolved_config_file = get_canonical_settings_path()
    if config_file != 'settings.json':
        logger.app_logger.warning(
            'Ignoring external config_file=%s; using canonical settings=%s',
            config_file,
            resolved_config_file,
        )

    config = AppConfig()

    from backend.core.config.api_key_manager import api_key_manager

    # Suppress API key manager side effects until JSON (and env) have been applied.
    # Otherwise get_llm_config() during load_from_env creates LLMConfig with the
    # default model and validates settings.json's key against
    # Google prefixes even when llm_model in that file is another provider.
    with api_key_manager.suppress_env_export_context():
        load_from_env(config, dict(os.environ))
        load_from_json(config, resolved_config_file)
        llm_cfg = config.get_llm_config()
        config.set_llm_config(
            llm_cfg.__class__.model_validate(llm_cfg.model_dump(exclude_none=True))
        )

    finalize_config(config)

    # CRITICAL: Sync the loaded config (which might have come from settings.json)
    # back to the APIKeyManager so that DirectLLMClient can find it.
    # Temporarily suppress env export to avoid double-setting during sync
    with api_key_manager.suppress_env_export_context():
        for llm_cfg in config.llms.values():
            if not llm_cfg.model or not str(llm_cfg.model).strip():
                continue
            if llm_cfg.api_key:
                api_key_manager.set_api_key(llm_cfg.model, llm_cfg.api_key)
                api_key_manager.set_environment_variables(
                    llm_cfg.model, llm_cfg.api_key
                )
            else:
                # If no key in config, try to load from environment
                provider = api_key_manager.extract_provider(llm_cfg.model)
                env_key = api_key_manager.get_provider_key_from_env(provider)
                if env_key:
                    llm_cfg.api_key = SecretStr(env_key)
                    api_key_manager.set_api_key(llm_cfg.model, llm_cfg.api_key)
                    api_key_manager.set_environment_variables(
                        llm_cfg.model, llm_cfg.api_key
                    )

    # Export all keys to environment after sync
    export_llm_api_keys(config)

    register_custom_agents(config)
    if set_logging_levels:
        logger.DEBUG = config.debug
        logger.DISABLE_COLOR_PRINTING = config.disable_color
    return config


def setup_config_from_args(args: argparse.Namespace) -> AppConfig:
    """Load config from toml and override with command line arguments.

    Configuration precedence (from highest to lowest):
    1. CLI parameters (e.g., -l for LLM config)
    2. Canonical repo-root ``settings.json`` only
    """
    config = load_app_config(config_file=args.config_file)
    apply_llm_config_override(config, args)
    apply_additional_overrides(config, args)
    return config
