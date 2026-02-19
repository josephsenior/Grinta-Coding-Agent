"""Tests for backend.core.config.mcp_config — MCP server config models."""

from __future__ import annotations

import pytest

from backend.core.config.mcp_config import (
    MCPConfig,
    MCPSHTTPServerConfig,
    MCPSSEServerConfig,
    MCPStdioServerConfig,
    _validate_mcp_url,
)


# ── _validate_mcp_url ───────────────────────────────────────────────


class TestValidateMcpUrl:
    def test_valid_http(self):
        assert _validate_mcp_url("http://localhost:8000") == "http://localhost:8000"

    def test_valid_https(self):
        assert _validate_mcp_url("https://example.com/mcp") == "https://example.com/mcp"

    def test_valid_ws(self):
        assert _validate_mcp_url("ws://localhost:8000") == "ws://localhost:8000"

    def test_valid_wss(self):
        assert _validate_mcp_url("wss://example.com") == "wss://example.com"

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            _validate_mcp_url("")

    def test_no_scheme_raises(self):
        with pytest.raises(ValueError):
            _validate_mcp_url("localhost:8000")

    def test_no_host_raises(self):
        with pytest.raises(ValueError):
            _validate_mcp_url("http://")

    def test_invalid_scheme_raises(self):
        with pytest.raises(ValueError, match="scheme must be"):
            _validate_mcp_url("ftp://example.com")

    def test_strips_whitespace(self):
        result = _validate_mcp_url("  https://example.com  ")
        assert result == "https://example.com"

    def test_generic_exception_reraise(self):
        """Test that non-ValueError exceptions are wrapped and raised."""
        from unittest.mock import patch

        with patch(
            "backend.core.config.mcp_config.urlparse",
            side_effect=RuntimeError("parse failed"),
        ):
            with pytest.raises(ValueError, match="Invalid URL format"):
                _validate_mcp_url("http://example.com")


# ── MCPSSEServerConfig ───────────────────────────────────────────────


class TestMCPSSEServerConfig:
    def test_valid(self):
        cfg = MCPSSEServerConfig(url="http://localhost:3000/sse")
        assert cfg.url == "http://localhost:3000/sse"
        assert cfg.api_key is None

    def test_with_api_key(self):
        cfg = MCPSSEServerConfig(url="https://example.com", api_key="key123")
        assert cfg.api_key == "key123"

    def test_invalid_url_raises(self):
        with pytest.raises(Exception):
            MCPSSEServerConfig(url="not-a-url")


# ── MCPStdioServerConfig ─────────────────────────────────────────────


class TestMCPStdioServerConfig:
    def test_valid(self):
        cfg = MCPStdioServerConfig(name="my-server", command="node")
        assert cfg.name == "my-server"
        assert cfg.command == "node"
        assert cfg.args == []
        assert cfg.env == {}

    def test_name_with_special_chars_raises(self):
        with pytest.raises(Exception, match="letters, numbers"):
            MCPStdioServerConfig(name="bad name!", command="node")

    def test_empty_name_raises(self):
        with pytest.raises(Exception):
            MCPStdioServerConfig(name="", command="node")

    def test_command_with_spaces_raises(self):
        with pytest.raises(Exception, match="single executable"):
            MCPStdioServerConfig(name="s1", command="node server.js")

    def test_empty_command_raises(self):
        with pytest.raises(Exception):
            MCPStdioServerConfig(name="s1", command="")

    def test_args_from_string(self):
        cfg = MCPStdioServerConfig(
            name="s1", command="npx", args="-y mcp-remote https://example.com"
        )
        assert cfg.args == ["-y", "mcp-remote", "https://example.com"]

    def test_args_from_string_with_quotes(self):
        cfg = MCPStdioServerConfig(
            name="s1", command="npx", args='--config "path with spaces"'
        )
        assert "--config" in cfg.args
        assert "path with spaces" in cfg.args

    def test_args_empty_string(self):
        cfg = MCPStdioServerConfig(name="s1", command="npx", args="")
        assert cfg.args == []

    def test_args_invalid_shlex_format(self):
        """Test handling of invalid shlex format in args."""
        with pytest.raises(Exception, match="Invalid argument format"):
            MCPStdioServerConfig(name="s1", command="npx", args='unclosed "quote')

    def test_env_from_string(self):
        cfg = MCPStdioServerConfig(name="s1", command="npx", env="FOO=bar,BAZ=qux")
        assert cfg.env == {"FOO": "bar", "BAZ": "qux"}

    def test_env_bad_format_raises(self):
        with pytest.raises(Exception, match="KEY=VALUE"):
            MCPStdioServerConfig(name="s1", command="npx", env="NOVALUE")

    def test_env_bad_key_raises(self):
        with pytest.raises(Exception, match="Invalid environment"):
            MCPStdioServerConfig(name="s1", command="npx", env="123BAD=val")

    def test_env_empty_string(self):
        """Test empty env string returns empty dict."""
        cfg = MCPStdioServerConfig(name="s1", command="npx", env="")
        assert cfg.env == {}

    def test_env_empty_pairs(self):
        """Test that empty pairs are skipped in env parsing."""
        cfg = MCPStdioServerConfig(name="s1", command="npx", env="FOO=bar,,BAZ=qux")
        assert cfg.env == {"FOO": "bar", "BAZ": "qux"}

    def test_env_empty_key(self):
        """Test that empty key raises error."""
        with pytest.raises(Exception, match="key cannot be empty"):
            MCPStdioServerConfig(name="s1", command="npx", env="=value")

    def test_equality_same(self):
        a = MCPStdioServerConfig(name="s", command="npx", args=["a"], env={"K": "V"})
        b = MCPStdioServerConfig(name="s", command="npx", args=["a"], env={"K": "V"})
        assert a == b

    def test_equality_different(self):
        a = MCPStdioServerConfig(name="s1", command="npx")
        b = MCPStdioServerConfig(name="s2", command="npx")
        assert a != b

    def test_equality_not_same_type(self):
        a = MCPStdioServerConfig(name="s1", command="npx")
        assert a != "not a config"


# ── MCPSHTTPServerConfig ─────────────────────────────────────────────


class TestMCPSHTTPServerConfig:
    def test_valid(self):
        cfg = MCPSHTTPServerConfig(url="http://localhost:3000/mcp")
        assert cfg.api_key is None

    def test_invalid_url_raises(self):
        with pytest.raises(Exception):
            MCPSHTTPServerConfig(url="bad")


# ── MCPConfig ────────────────────────────────────────────────────────


class TestMCPConfig:
    def test_defaults(self):
        cfg = MCPConfig()
        assert cfg.sse_servers == []
        assert cfg.stdio_servers == []
        assert cfg.shttp_servers == []

    def test_extra_field_rejected(self):
        with pytest.raises(Exception):
            MCPConfig(unknown="x")

    def test_normalize_servers_string_urls(self):
        normalized = MCPConfig._normalize_servers(["http://example.com"])
        assert normalized == [{"url": "http://example.com"}]

    def test_normalize_servers_dict_passthrough(self):
        data = [{"url": "http://example.com", "api_key": "k"}]
        normalized = MCPConfig._normalize_servers(data)
        assert normalized == data

    def test_string_url_conversion(self):
        cfg = MCPConfig.model_validate(
            {
                "sse_servers": ["http://example.com:3000/sse"],
            }
        )
        assert len(cfg.sse_servers) == 1
        assert cfg.sse_servers[0].url == "http://example.com:3000/sse"

    def test_validate_servers_duplicate_raises(self):
        cfg = MCPConfig(
            sse_servers=[
                MCPSSEServerConfig(url="http://example.com"),
                MCPSSEServerConfig(url="http://example.com"),
            ]
        )
        with pytest.raises(ValueError, match="Duplicate"):
            cfg.validate_servers()

    def test_validate_servers_ok(self):
        cfg = MCPConfig(
            sse_servers=[
                MCPSSEServerConfig(url="http://a.com"),
                MCPSSEServerConfig(url="http://b.com"),
            ]
        )
        cfg.validate_servers()  # Should not raise

    def test_validate_servers_invalid_url_format(self):
        """Test validate_servers with malformed URL."""
        from unittest.mock import patch

        cfg = MCPConfig(sse_servers=[MCPSSEServerConfig(url="http://test.com")])
        # Patch urlparse to make it fail for testing exception path
        with patch(
            "backend.core.config.mcp_config.urlparse",
            side_effect=Exception("parse error"),
        ):
            with pytest.raises(ValueError, match="Invalid URL"):
                cfg.validate_servers()

    def test_merge(self):
        a = MCPConfig(sse_servers=[MCPSSEServerConfig(url="http://a.com")])
        b = MCPConfig(sse_servers=[MCPSSEServerConfig(url="http://b.com")])
        merged = a.merge(b)
        assert len(merged.sse_servers) == 2

    def test_from_toml_section_empty(self):
        mapping = MCPConfig.from_toml_section({})
        assert "mcp" in mapping
        cfg = mapping["mcp"]
        assert cfg.sse_servers == []

    def test_from_toml_section_sse(self):
        mapping = MCPConfig.from_toml_section(
            {
                "sse_servers": [{"url": "http://localhost:3000/sse"}],
            }
        )
        assert len(mapping["mcp"].sse_servers) == 1

    def test_from_toml_section_stdio(self):
        mapping = MCPConfig.from_toml_section(
            {
                "stdio_servers": [{"name": "s1", "command": "npx"}],
            }
        )
        assert len(mapping["mcp"].stdio_servers) == 1

    def test_from_toml_section_shttp(self):
        """Test from_toml_section with shttp_servers."""
        mapping = MCPConfig.from_toml_section(
            {
                "shttp_servers": [{"url": "http://localhost:3000/mcp"}],
            }
        )
        assert len(mapping["mcp"].shttp_servers) == 1
        assert mapping["mcp"].shttp_servers[0].url == "http://localhost:3000/mcp"

    def test_from_toml_section_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid MCP configuration"):
            MCPConfig.from_toml_section({"unknown_field": True})


class TestForgeMCPConfig:
    def test_create_default_mcp_server_config(self):
        """Test create_default_mcp_server_config."""
        from backend.core.config.mcp_config import ForgeMCPConfig
        from backend.core.config.forge_config import ForgeConfig

        config = ForgeConfig()
        shttp, stdio = ForgeMCPConfig.create_default_mcp_server_config(
            "localhost:3000", config, "user123"
        )
        assert shttp is not None
        assert shttp.url == "http://localhost:3000/mcp/mcp"
        assert isinstance(stdio, list)
        assert not stdio
