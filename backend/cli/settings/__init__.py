"""App settings I/O, onboarding, and programmatic updates."""

from backend.cli.settings.constants import (
    _PROVIDERS,
    DEFAULT_MODEL_BY_PROVIDER,
    DEFAULT_ONBOARDING_MODEL,
)
from backend.cli.settings.mcp import (
    add_mcp_server,
    get_mcp_server,
    get_mcp_servers,
    mcp_server_endpoint,
    remove_mcp_server,
    set_mcp_server_enabled,
    update_mcp_server,
)

from backend.cli.onboarding import (
    _test_llm_call,  # noqa: F401
    auto_detect_api_keys,
    needs_onboarding,
    persist_env_detected_settings,
    run_onboarding,
)
from backend.cli.settings.query import (
    ensure_default_model,
    get_budget,
    get_cli_tool_icons_enabled,
    get_current_model,
    get_current_provider,
    get_masked_api_key,
    get_persisted_autonomy_level,
    get_persisted_interaction_mode,
    get_persisted_reasoning_effort,
    sync_persisted_autonomy_to_controller,
    sync_persisted_interaction_mode_to_controller,
    update_api_key,
    update_autonomy_level,
    update_budget,
    update_cli_tool_icons,
    update_interaction_mode,
    update_model,
    update_reasoning_effort,
)
from backend.cli.settings.storage import (
    _load_raw_settings,
    _save_raw_settings,
    _settings_path,
)

__all__ = [
    'DEFAULT_MODEL_BY_PROVIDER',
    'DEFAULT_ONBOARDING_MODEL',
    '_PROVIDERS',
    '_load_raw_settings',
    '_save_raw_settings',
    '_settings_path',
    '_test_llm_call',
    'add_mcp_server',
    'auto_detect_api_keys',
    'ensure_default_model',
    'get_budget',
    'get_cli_tool_icons_enabled',
    'get_current_model',
    'get_current_provider',
    'get_masked_api_key',
    'get_mcp_server',
    'get_mcp_servers',
    'get_persisted_autonomy_level',
    'get_persisted_interaction_mode',
    'get_persisted_reasoning_effort',
    'mcp_server_endpoint',
    'sync_persisted_autonomy_to_controller',
    'sync_persisted_interaction_mode_to_controller',
    'persist_env_detected_settings',
    'needs_onboarding',
    'remove_mcp_server',
    'run_onboarding',
    'set_mcp_server_enabled',
    'update_api_key',
    'update_autonomy_level',
    'update_budget',
    'update_cli_tool_icons',
    'update_interaction_mode',
    'update_model',
    'update_mcp_server',
    'update_reasoning_effort',
]
