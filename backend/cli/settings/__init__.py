"""App settings I/O, onboarding, and programmatic updates."""

from backend.cli.settings.constants import (
    DEFAULT_MODEL_BY_PROVIDER,
    DEFAULT_ONBOARDING_MODEL,
    _PROVIDERS,
)
from backend.cli.settings.mcp import add_mcp_server, get_mcp_servers, remove_mcp_server
from backend.cli.settings.onboarding import (
    auto_detect_api_keys,
    needs_onboarding,
    run_onboarding,
)
from backend.cli.settings.query import (
    ensure_default_model,
    get_budget,
    get_cli_tool_icons_enabled,
    get_current_model,
    get_current_provider,
    get_masked_api_key,
    get_persisted_reasoning_effort,
    update_api_key,
    update_budget,
    update_cli_tool_icons,
    update_model,
    update_reasoning_effort,
)
from backend.cli.settings.storage import (
    _load_raw_settings,
    _save_raw_settings,
    _settings_path,
)

# Test hook
from backend.cli.settings.onboarding import _test_llm_call  # noqa: F401

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
    'get_mcp_servers',
    'get_persisted_reasoning_effort',
    'needs_onboarding',
    'remove_mcp_server',
    'run_onboarding',
    'update_api_key',
    'update_budget',
    'update_cli_tool_icons',
    'update_model',
    'update_reasoning_effort',
]
