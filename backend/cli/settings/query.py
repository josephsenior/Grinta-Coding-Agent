"""Settings queries and programmatic updates."""

from __future__ import annotations

import logging
import os
from typing import Any

from rich.console import Console

from backend.cli.theme import (
    no_color_enabled,
)
from backend.core.config import AppConfig
from backend.core.config.dotenv_keys import (
    persist_llm_api_key_to_dotenv,
    persist_provider_api_key_to_dotenv,
)
from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER

logger = logging.getLogger(__name__)
_console = Console(no_color=no_color_enabled())

from backend.cli.onboarding.flow import (
    _default_model_for_api_key,
    _default_model_from_environment,
)
from backend.cli.settings.storage import (
    _load_raw_settings,
    _save_raw_settings,
    _settings_path,
)


def ensure_default_model(config: AppConfig) -> str | None:
    """Ensure the active LLM config has a usable model when a key exists."""
    llm_cfg = config.get_llm_config()
    model = (getattr(llm_cfg, 'model', None) or '').strip()
    if model:
        return model

    raw_key = _resolve_api_key_value(config)
    if raw_key:
        inferred_model = _default_model_for_api_key(raw_key)
        llm_cfg.model = inferred_model
        return inferred_model

    env_model = _default_model_from_environment()
    if not env_model:
        return None
    llm_cfg.model = env_model
    return env_model


def get_current_model(config: AppConfig) -> str:
    try:
        return config.get_llm_config().model or '(not set)'
    except Exception:
        logger.debug('Could not read current model from config', exc_info=True)
        return '(not set)'


def get_current_provider(config: AppConfig) -> str | None:
    try:
        from backend.inference.provider_resolver import extract_provider_prefix

        llm_cfg = config.get_llm_config()
        raw_provider = getattr(llm_cfg, 'custom_llm_provider', None)
        configured = _sanitize_llm_provider(raw_provider) or ''
        if configured:
            return configured
        model = (getattr(llm_cfg, 'model', None) or '').strip()
        if not model:
            return None
        prefixed = extract_provider_prefix(model)
        if prefixed:
            return prefixed
        from backend.inference.catalog.catalog_loader import lookup

        entry = lookup(model)
        return entry.provider if entry else None
    except Exception:
        logger.debug('Could not read current provider from config', exc_info=True)
        return None


def _resolve_api_key_value(
    config: AppConfig, provider: str | None = None
) -> str | None:
    if provider:
        try:
            from backend.core.config.api_key_manager import api_key_manager

            provider_key = api_key_manager.get_provider_key_from_env(provider)
            if provider_key and provider_key.strip():
                return provider_key.strip()
        except Exception:
            logger.debug('Could not resolve provider API key', exc_info=True)

    llm_cfg = config.get_llm_config()
    raw = _api_key_from_llm_cfg(llm_cfg)
    if raw:
        return raw

    model = (getattr(llm_cfg, 'model', '') or '').strip()
    env_raw = _api_key_from_env_for_model(model) if model else None
    if env_raw:
        return env_raw

    fallback = (os.environ.get('LLM_API_KEY') or '').strip()
    return fallback or None


def _api_key_from_llm_cfg(llm_cfg: Any) -> str | None:
    api_key: Any = getattr(llm_cfg, 'api_key', None)
    if api_key is None:
        return None
    try:
        raw = api_key.get_secret_value()
    except AttributeError:
        raw = str(api_key)
    raw = raw.strip()
    return raw or None


def _api_key_from_env_for_model(model: str) -> str | None:
    try:
        from backend.core.config.api_key_manager import api_key_manager

        provider = api_key_manager.extract_provider(model)
        env_key = api_key_manager.get_provider_key_from_env(provider)
        if env_key and env_key.strip():
            return env_key.strip()
    except Exception:
        logger.debug('Could not resolve env-backed API key', exc_info=True)
    return None


def _mask_secret(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return '(not set)'
    if len(raw) <= 4:
        return '•' * len(raw)
    if len(raw) <= 8:
        visible = 2
        return raw[:visible] + '•' * (len(raw) - (visible * 2)) + raw[-visible:]
    return raw[:4] + '•' * min(len(raw) - 8, 20) + raw[-4:]


def get_masked_api_key(config: AppConfig, provider: str | None = None) -> str:
    try:
        raw = _resolve_api_key_value(config, provider)
        if not raw:
            return '(not set)'
        return _mask_secret(raw)
    except Exception:
        logger.debug('Could not read API key for masking', exc_info=True)
        return '(not set)'


def _sanitize_llm_provider(value: Any) -> str | None:
    """Return a safe provider slug for settings.json, or None if invalid."""
    if value is None:
        return None
    if not isinstance(value, str):
        module = getattr(type(value), '__module__', '')
        if module.startswith('unittest.mock'):
            return None
        value = str(value)
    text = value.strip().lower()
    if not text or 'magicmock' in text or text.startswith('<'):
        return None
    return text


def get_persisted_reasoning_effort() -> str:
    """Return the user-configured reasoning effort from settings.json (empty = default)."""
    raw = _load_raw_settings().get('llm_reasoning_effort')
    if raw is None:
        return ''
    return str(raw).strip()


def sync_persisted_autonomy_to_controller(
    controller: Any,
    agent_name: str | None = None,
    *,
    config: Any | None = None,
) -> str:
    """Apply settings.json autonomy to the live controller.

    Returns the effective autonomy level on the controller after sync.
    When no persisted value exists, returns the controller's current level.
    """
    from backend.core.autonomy import normalize_autonomy_level
    from backend.core.constants import DEFAULT_AGENT_NAME

    level = get_persisted_autonomy_level(agent_name)
    if not level:
        ac = getattr(controller, 'autonomy_controller', None)
        return normalize_autonomy_level(
            getattr(ac, 'autonomy_level', 'balanced') if ac is not None else 'balanced'
        )

    target_agent = (agent_name or DEFAULT_AGENT_NAME).strip() or DEFAULT_AGENT_NAME
    ac = getattr(controller, 'autonomy_controller', None)
    if ac is not None:
        ac.autonomy_level = level

    if config is not None:
        try:
            setattr(config, 'autonomy_level', level)
            getter = getattr(config, 'get_agent_config', None)
            if callable(getter):
                try:
                    agent_config = getter(target_agent)
                except TypeError:
                    agent_config = getter()
                if agent_config is not None:
                    agent_config.autonomy_level = level
        except Exception:
            logger.debug(
                'Could not mirror persisted autonomy onto config',
                exc_info=True,
            )

    from backend.cli.settings.mode_runtime import apply_autonomy_to_controller

    apply_autonomy_to_controller(controller)

    try:
        from backend.core.logging.session_event_logger import (
            emit_session_context_if_changed,
        )

        emit_session_context_if_changed()
    except Exception:
        pass

    return level


def sync_persisted_interaction_mode_to_controller(
    controller: Any,
    agent_name: str | None = None,
    *,
    config: Any | None = None,
) -> str:
    """Apply settings.json interaction mode to the live controller.

    Returns the effective mode on the controller after sync.
    """
    from backend.cli.settings.mode_runtime import apply_interaction_mode_to_controller
    from backend.core.constants import DEFAULT_AGENT_NAME
    from backend.core.interaction_modes import normalize_interaction_mode

    mode = get_persisted_interaction_mode(agent_name)
    if not mode:
        agent = getattr(controller, 'agent', None)
        running_config = getattr(agent, 'config', None) if agent is not None else None
        if running_config is not None:
            return normalize_interaction_mode(getattr(running_config, 'mode', None))
        if config is not None:
            try:
                target = (
                    agent_name or DEFAULT_AGENT_NAME
                ).strip() or DEFAULT_AGENT_NAME
                agent_config = config.get_agent_config(target)
                return normalize_interaction_mode(getattr(agent_config, 'mode', None))
            except Exception:
                logger.debug(
                    'Could not read interaction mode from config during sync',
                    exc_info=True,
                )
        return 'agent'

    target_agent = (agent_name or DEFAULT_AGENT_NAME).strip() or DEFAULT_AGENT_NAME
    if config is not None:
        try:
            agent_config = config.get_agent_config(target_agent)
            agent_config.mode = mode
            setattr(config, 'mode', mode)
        except Exception:
            logger.debug(
                'Could not mirror persisted interaction mode onto config',
                exc_info=True,
            )

    apply_interaction_mode_to_controller(controller, mode)
    return mode


def get_persisted_autonomy_level(agent_name: str | None = None) -> str:
    """Return the user-configured autonomy level from settings.json (empty = default)."""
    from backend.core.autonomy import (
        _VALID_AUTONOMY_LEVELS,
        resolve_persisted_autonomy_level,
    )
    from backend.core.constants import DEFAULT_AGENT_NAME

    agent_section = _load_raw_settings().get('agent')
    if not isinstance(agent_section, dict):
        return ''

    candidate_names: list[str] = []
    if agent_name and agent_name.strip():
        candidate_names.append(agent_name.strip())
    for fallback in (DEFAULT_AGENT_NAME, 'agent'):
        if fallback not in candidate_names:
            candidate_names.append(fallback)
    for name, entry in agent_section.items():
        if (
            isinstance(name, str)
            and isinstance(entry, dict)
            and 'autonomy_level' in entry
            and name not in candidate_names
        ):
            candidate_names.append(name)

    for name in candidate_names:
        entry = agent_section.get(name)
        if not isinstance(entry, dict):
            continue
        raw = entry.get('autonomy_level')
        level = resolve_persisted_autonomy_level(raw)
        if level in _VALID_AUTONOMY_LEVELS:
            return level
    return ''


def update_autonomy_level(level: str, agent_name: str | None = None) -> None:
    """Persist autonomy level without touching other agent fields."""
    from backend.core.autonomy import (
        _VALID_AUTONOMY_LEVELS,
        resolve_persisted_autonomy_level,
    )
    from backend.core.constants import DEFAULT_AGENT_NAME

    normalized = resolve_persisted_autonomy_level(level)
    if normalized not in _VALID_AUTONOMY_LEVELS:
        return

    target_agent = (agent_name or DEFAULT_AGENT_NAME).strip() or DEFAULT_AGENT_NAME
    settings = _load_raw_settings()
    agent_section = settings.get('agent')
    if not isinstance(agent_section, dict):
        agent_section = {}
    agent_entry = agent_section.get(target_agent)
    if not isinstance(agent_entry, dict):
        agent_entry = {}
    agent_entry['autonomy_level'] = normalized
    agent_section[target_agent] = agent_entry
    settings['agent'] = agent_section
    _save_raw_settings(settings)


def get_persisted_interaction_mode(agent_name: str | None = None) -> str:
    """Return the user-configured interaction mode from settings.json (empty = default)."""
    from backend.core.constants import DEFAULT_AGENT_NAME
    from backend.core.interaction_modes import normalize_interaction_mode

    agent_section = _load_raw_settings().get('agent')
    if not isinstance(agent_section, dict):
        return ''

    candidate_names: list[str] = []
    if agent_name and agent_name.strip():
        candidate_names.append(agent_name.strip())
    for fallback in (DEFAULT_AGENT_NAME, 'agent'):
        if fallback not in candidate_names:
            candidate_names.append(fallback)
    for name, entry in agent_section.items():
        if (
            isinstance(name, str)
            and isinstance(entry, dict)
            and 'mode' in entry
            and name not in candidate_names
        ):
            candidate_names.append(name)

    for name in candidate_names:
        entry = agent_section.get(name)
        if not isinstance(entry, dict):
            continue
        mode = normalize_interaction_mode(entry.get('mode'), default='')
        if mode:
            return mode
    return ''


def _update_agent_bool_field(
    field: str,
    value: bool,
    agent_name: str | None = None,
) -> None:
    """Persist a single boolean field on the active agent entry."""
    from backend.core.constants import DEFAULT_AGENT_NAME

    target_agent = (agent_name or DEFAULT_AGENT_NAME).strip() or DEFAULT_AGENT_NAME
    settings = _load_raw_settings()
    agent_section = settings.get('agent')
    if not isinstance(agent_section, dict):
        agent_section = {}
    agent_entry = agent_section.get(target_agent)
    if not isinstance(agent_entry, dict):
        agent_entry = {}
    agent_entry[field] = bool(value)
    agent_section[target_agent] = agent_entry
    settings['agent'] = agent_section
    _save_raw_settings(settings)


def update_enable_lsp_query(enabled: bool, agent_name: str | None = None) -> None:
    """Persist ``lsp_config.enabled``."""
    from backend.core.config.tool_integration_defaults import default_lsp_config

    _ = agent_name
    settings = _load_raw_settings()
    lsp_cfg = settings.get('lsp_config')
    if not isinstance(lsp_cfg, dict):
        lsp_cfg = dict(default_lsp_config())
    lsp_cfg['enabled'] = bool(enabled)
    settings['lsp_config'] = lsp_cfg
    _save_raw_settings(settings)


def update_enable_debugger(enabled: bool, agent_name: str | None = None) -> None:
    """Persist ``dap_config.enabled``."""
    from backend.core.config.tool_integration_defaults import default_dap_config

    _ = agent_name
    settings = _load_raw_settings()
    dap_cfg = settings.get('dap_config')
    if not isinstance(dap_cfg, dict):
        dap_cfg = dict(default_dap_config())
    dap_cfg['enabled'] = bool(enabled)
    settings['dap_config'] = dap_cfg
    _save_raw_settings(settings)


def update_interaction_mode(mode: str, agent_name: str | None = None) -> None:
    """Persist interaction mode without touching other agent fields."""
    from backend.core.constants import DEFAULT_AGENT_NAME
    from backend.core.interaction_modes import (
        VALID_INTERACTION_MODES,
        normalize_interaction_mode,
    )

    normalized = normalize_interaction_mode(mode)
    if normalized not in VALID_INTERACTION_MODES:
        return

    target_agent = (agent_name or DEFAULT_AGENT_NAME).strip() or DEFAULT_AGENT_NAME
    settings = _load_raw_settings()
    agent_section = settings.get('agent')
    if not isinstance(agent_section, dict):
        agent_section = {}
    agent_entry = agent_section.get(target_agent)
    if not isinstance(agent_entry, dict):
        agent_entry = {}
    agent_entry['mode'] = normalized
    agent_section[target_agent] = agent_entry
    settings['agent'] = agent_section
    _save_raw_settings(settings)


def update_reasoning_effort(effort: str | None) -> None:
    """Persist reasoning effort without touching model or provider fields."""
    settings = _load_raw_settings()
    if effort and str(effort).strip():
        settings['llm_reasoning_effort'] = str(effort).strip()
    else:
        settings.pop('llm_reasoning_effort', None)
    _save_raw_settings(settings)


def update_model(
    model: str,
    provider: str | None = None,
    base_url: str | None = None,
    reasoning_effort: str | None = None,
    clear_base_url: bool = False,
) -> None:
    settings = _load_raw_settings()
    settings['llm_model'] = model
    provider = _sanitize_llm_provider(provider)
    if provider:
        settings['llm_provider'] = provider
    if base_url:
        settings['llm_base_url'] = base_url
    elif clear_base_url:
        settings.pop('llm_base_url', None)
    if reasoning_effort and str(reasoning_effort).strip():
        settings['llm_reasoning_effort'] = str(reasoning_effort).strip()
    else:
        settings.pop('llm_reasoning_effort', None)
    _save_raw_settings(settings)


def update_api_key(key: str, provider: str | None = None) -> None:
    settings = _load_raw_settings()
    settings['llm_api_key'] = LLM_API_KEY_SETTINGS_PLACEHOLDER
    _save_raw_settings(settings)
    if provider and provider.strip():
        persist_provider_api_key_to_dotenv(
            provider.strip().lower(), key, settings_json_path=_settings_path()
        )
    persist_llm_api_key_to_dotenv(key, settings_json_path=_settings_path())


def update_budget(budget: float | None) -> None:
    settings = _load_raw_settings()
    if budget is None or budget <= 0:
        settings.pop('max_budget_per_task', None)
    else:
        settings['max_budget_per_task'] = budget
    _save_raw_settings(settings)


def update_cli_tool_icons(enabled: bool) -> None:
    settings = _load_raw_settings()
    settings['cli_tool_icons'] = bool(enabled)
    _save_raw_settings(settings)


def get_cli_tool_icons_enabled(config: AppConfig) -> bool:
    return bool(getattr(config, 'cli_tool_icons', True))


def get_budget(config: AppConfig) -> str:
    budget = getattr(config, 'max_budget_per_task', None)
    if budget is None:
        return 'unlimited'
    return f'${budget:.2f}'
