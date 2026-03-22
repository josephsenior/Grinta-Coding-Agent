"""Tests for backend.core.constants — core constant values and _parse_bool_env."""

from __future__ import annotations

import os
from unittest.mock import patch

from backend.core.constants import (
    API_VERSION_V1,
    CONVERSATION_BASE_DIR,
    CURRENT_API_VERSION,
    DEFAULT_AGENT_AUTONOMY_LEVEL,
    DEFAULT_AGENT_MEMORY_MAX_THREADS,
    DEFAULT_AGENT_MIN_ITERATIONS,
    DEFAULT_CMD_EXIT_CODE,
    DEFAULT_CONFIG_FILE,
    DEFAULT_CONVERSATION_MAX_AGE_SECONDS,
    DEFAULT_FILE_STORE,
    DEFAULT_INDENT_SIZES,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_MAX_CONCURRENT_CONVERSATIONS,
    DEFAULT_MAX_FILE_UPLOAD_SIZE_MB,
    DEFAULT_RUNTIME,
    DEFAULT_RUNTIME_TIMEOUT,
    DEFAULT_LOCAL_DATA_ROOT,
    ENV_VAR_REGISTRY,
    FILES_TO_IGNORE,
    FORGE_DEFAULT_AGENT,
    FORGE_MAX_ITERATIONS,
    LOG_COLORS,
    MAX_CMD_OUTPUT_SIZE,
    MAX_FILENAME_LENGTH,
    MAX_PATH_LENGTH,
    MCP_CACHEABLE_TOOLS,
    RISK_LEVELS,
    SECRET_PLACEHOLDER,
    SETTINGS_CACHE_TTL,
    _parse_bool_env,
)


# ── _parse_bool_env ──────────────────────────────────────────────────


class TestParseBoolEnv:
    def test_true_variants(self):
        for val in ("true", "True", "TRUE", "1", "yes", "YES"):
            with patch.dict(os.environ, {"TEST_VAR": val}):
                assert _parse_bool_env("TEST_VAR") is True

    def test_false_variants(self):
        for val in ("false", "False", "0", "no", "NO", ""):
            with patch.dict(os.environ, {"TEST_VAR": val}):
                assert _parse_bool_env("TEST_VAR") is False

    def test_unset_defaults_false(self):
        env = os.environ.copy()
        env.pop("NONEXISTENT_VAR_12345", None)
        with patch.dict(os.environ, env, clear=True):
            assert _parse_bool_env("NONEXISTENT_VAR_12345") is False

    def test_custom_default_true(self):
        env = os.environ.copy()
        env.pop("NONEXISTENT_VAR_12345", None)
        with patch.dict(os.environ, env, clear=True):
            assert _parse_bool_env("NONEXISTENT_VAR_12345", default="true") is True

    def test_whitespace_stripped(self):
        with patch.dict(os.environ, {"TEST_VAR": "  true  "}):
            assert _parse_bool_env("TEST_VAR") is True

    def test_random_string_false(self):
        with patch.dict(os.environ, {"TEST_VAR": "banana"}):
            assert _parse_bool_env("TEST_VAR") is False


# ── Constant Type / Value Assertions ────────────────────────────────


class TestCoreConstants:
    def test_identity_constants(self):
        assert FORGE_DEFAULT_AGENT == "Orchestrator"
        assert isinstance(FORGE_MAX_ITERATIONS, int)
        assert FORGE_MAX_ITERATIONS > 0

    def test_path_constants(self):
        assert DEFAULT_CONFIG_FILE == "settings.json"
        assert isinstance(DEFAULT_LOCAL_DATA_ROOT, str)

    def test_security(self):
        assert SECRET_PLACEHOLDER == "**********"
        assert RISK_LEVELS == ["LOW", "MEDIUM", "HIGH"]

    def test_cache_ttl(self):
        assert SETTINGS_CACHE_TTL == 60

    def test_runtime_defaults(self):
        assert DEFAULT_RUNTIME == "local"
        assert DEFAULT_FILE_STORE == "local"
        assert isinstance(DEFAULT_RUNTIME_TIMEOUT, int)
        assert DEFAULT_RUNTIME_TIMEOUT > 0

    def test_llm_defaults(self):
        assert isinstance(DEFAULT_LLM_MODEL, str)
        assert DEFAULT_LLM_TEMPERATURE == 0.0

    def test_agent_defaults(self):
        assert DEFAULT_AGENT_AUTONOMY_LEVEL == "balanced"
        assert isinstance(DEFAULT_AGENT_MEMORY_MAX_THREADS, int)
        assert isinstance(DEFAULT_AGENT_MIN_ITERATIONS, int)

    def test_api_version(self):
        assert API_VERSION_V1 == "v1"
        assert CURRENT_API_VERSION == API_VERSION_V1

    def test_storage(self):
        assert CONVERSATION_BASE_DIR == "sessions"
        assert DEFAULT_CONVERSATION_MAX_AGE_SECONDS > 0
        assert DEFAULT_MAX_CONCURRENT_CONVERSATIONS > 0

    def test_file_upload(self):
        assert DEFAULT_MAX_FILE_UPLOAD_SIZE_MB > 0
        assert isinstance(FILES_TO_IGNORE, list)
        assert ".git/" in FILES_TO_IGNORE

    def test_cmd_output(self):
        assert DEFAULT_CMD_EXIT_CODE == -1
        assert MAX_CMD_OUTPUT_SIZE > 0

    def test_log_colors(self):
        assert isinstance(LOG_COLORS, dict)
        assert "ACTION" in LOG_COLORS
        assert "ERROR" in LOG_COLORS

    def test_indent_sizes(self):
        assert isinstance(DEFAULT_INDENT_SIZES, dict)
        assert DEFAULT_INDENT_SIZES["python"] == 4
        assert DEFAULT_INDENT_SIZES["javascript"] == 2

    def test_mcp_cacheable_tools(self):
        assert isinstance(MCP_CACHEABLE_TOOLS, set)
        assert "get_component" in MCP_CACHEABLE_TOOLS

    def test_path_limits(self):
        assert MAX_FILENAME_LENGTH == 255
        assert MAX_PATH_LENGTH == 4096


# ── ENV_VAR_REGISTRY ────────────────────────────────────────────────


class TestEnvVarRegistry:
    def test_is_dict(self):
        assert isinstance(ENV_VAR_REGISTRY, dict)

    def test_entries_are_tuples(self):
        for key, val in ENV_VAR_REGISTRY.items():
            assert isinstance(key, str), f"Key {key} is not str"
            assert isinstance(val, tuple), f"Value for {key} is not tuple"
            assert len(val) == 2, f"Value for {key} does not have 2 elements"
            assert isinstance(val[0], str), f"Default for {key} is not str"
            assert isinstance(val[1], str), f"Description for {key} is not str"

    def test_known_keys_present(self):
        assert "LOG_LEVEL" in ENV_VAR_REGISTRY
        assert "DEBUG" in ENV_VAR_REGISTRY
        assert "FORGE_PERMISSIVE_API" in ENV_VAR_REGISTRY
