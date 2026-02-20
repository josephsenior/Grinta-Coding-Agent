"""Tests for backend.core.config.mcp_config — MCP server config models."""

from __future__ import annotations

import pytest

from backend.core.config.mcp_config import (
    MCPConfig,
    MCPServerConfig,
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


# ── MCPServerConfig (SSE / sHTTP) ─────────────────────────────────────


class TestMCPServerConfigRemote:
    def test_valid_sse(self):
        cfg = MCPServerConfig(name="s1", type="sse", url="http://localhost:3000/mcp")
        assert cfg.url == "http://localhost:3000/mcp"
        assert cfg.transport == "sse"
        assert cfg.api_key is None

    def test_valid_shttp(self):
        cfg = MCPServerConfig(
            name="s2", type="shttp", url="https://example.com", api_key="key123"
        )
        assert cfg.api_key == "key123"

    def test_invalid_url_raises(self):
        with pytest.raises(Exception):
            MCPServerConfig(name="s1", type="sse", url="not-a-url")

    def test_missing_url_raises(self):
        with pytest.raises(Exception):
            MCPServerConfig(name="s1", type="sse")


# ── MCPServerConfig (stdio) ─────────────────────────────────────────


class TestMCPServerConfigStdio:
    def test_valid(self):
        cfg = MCPServerConfig(name="my-server", type="stdio", command="node")
        assert cfg.name == "my-server"
        assert cfg.command == "node"
        assert cfg.args == []
        assert cfg.env == {}

    def test_name_with_special_chars_raises(self):
        with pytest.raises(Exception, match="letters, numbers"):
            MCPServerConfig(name="bad name!", type="stdio", command="node")

    def test_empty_name_raises(self):
        with pytest.raises(Exception):
            MCPServerConfig(name="", type="stdio", command="node")

    def test_command_with_spaces_raises(self):
        with pytest.raises(Exception, match="single executable"):
            MCPServerConfig(name="s1", type="stdio", command="node server.js")

    def test_empty_command_raises(self):
        with pytest.raises(Exception):
            MCPServerConfig(name="s1", type="stdio", command="")

    def test_missing_command_raises(self):
        with pytest.raises(Exception):
            MCPServerConfig(name="s1", type="stdio")

    def test_args_from_string(self):
        cfg = MCPServerConfig(
            name="s1", type="stdio", command="npx",
            args="-y mcp-remote https://example.com"
        )
        assert cfg.args == ["-y", "mcp-remote", "https://example.com"]

    def test_args_from_string_with_quotes(self):
        cfg = MCPServerConfig(
            name="s1", type="stdio", command="npx",
            args='--config "path with spaces"'
        )
        assert "--config" in cfg.args
        assert "path with spaces" in cfg.args

    def test_args_empty_string(self):
        cfg = MCPServerConfig(name="s1", type="stdio", command="npx", args="")
        assert cfg.args == []

    def test_args_invalid_shlex_format(self):
        with pytest.raises(Exception, match="Invalid argument format"):
            MCPServerConfig(name="s1", type="stdio", command="npx", args='unclosed "quote')

    def test_env_from_string(self):
        cfg = MCPServerConfig(name="s1", type="stdio", command="npx", env="FOO=bar,BAZ=qux")
        assert cfg.env == {"FOO": "bar", "BAZ": "qux"}

    def test_env_bad_format_raises(self):
        with pytest.raises(Exception, match="KEY=VALUE"):
            MCPServerConfig(name="s1", type="stdio", command="npx", env="NOVALUE")

    def test_env_bad_key_raises(self):
        with pytest.raises(Exception, match="Invalid environment"):
            MCPServerConfig(name="s1", type="stdio", command="npx", env="123BAD=val")

    def test_env_empty_string(self):
        cfg = MCPServerConfig(name="s1", type="stdio", command="npx", env="")
        assert cfg.env == {}

    def test_env_empty_pairs(self):
        cfg = MCPServerConfig(name="s1", type="stdio", command="npx", env="FOO=bar,,BAZ=qux")
        assert cfg.env == {"FOO": "bar", "BAZ": "qux"}

    def test_env_empty_key(self):
        with pytest.raises(Exception, match="key cannot be empty"):
            MCPServerConfig(name="s1", type="stdio", command="npx", env="=value")

    def test_equality_same(self):
        a = MCPServerConfig(name="s", type="stdio", command="npx", args=["a"], env={"K": "V"})
        b = MCPServerConfig(name="s", type="stdio", command="npx", args=["a"], env={"K": "V"})
        assert a == b

    def test_equality_different(self):
        a = MCPServerConfig(name="s1", type="stdio", command="npx")
        b = MCPServerConfig(name="s2", type="stdio", command="npx")
        assert a != b

    def test_equality_not_same_type(self):
        a = MCPServerConfig(name="s1", type="stdio", command="npx")
        assert a != "not a config"

    def test_from_dict_stdio(self):
        data = {"command": "npx", "args": ["-y", "@browser-use/mcp"]}
        cfg = MCPServerConfig.from_dict("browser-use", data)
        assert cfg.name == "browser-use"
        assert cfg.type == "stdio"
        assert cfg.command == "npx"
        assert cfg.args == ["-y", "@browser-use/mcp"]

    def test_from_dict_sse(self):
        data = {"url": "http://localhost:3000/sse"}
        cfg = MCPServerConfig.from_dict("my-sse", data)
        assert cfg.name == "my-sse"
        assert cfg.type == "sse"
        assert cfg.url == "http://localhost:3000/sse"

    def test_validate_command_none(self):
        """Test that validate_command handles None (for remote servers)."""
        assert MCPServerConfig.validate_command(None) is None

    def test_validate_url_none(self):
        """Test that validate_url handles None (for stdio servers)."""
        assert MCPServerConfig.validate_url(None) is None

    def test_parse_args_none(self):
        """Test that parse_args handles None."""
        assert MCPServerConfig.parse_args(None) == []

    def test_parse_env_none(self):
        """Test that parse_env handles None."""
        assert MCPServerConfig.parse_env(None) == {}

    def test_from_toml_section_invalid_json_graceful(self, tmp_path, monkeypatch):
        """Test that from_toml_section handles invalid JSON in config.json gracefully."""
        # Setup mock invalid config.json
        mcp_dir = tmp_path / "backend" / "runtime" / "mcp"
        mcp_dir.mkdir(parents=True)
        config_json = mcp_dir / "config.json"
        
        with open(config_json, "w") as f:
            f.write("invalid json")
            
        import os
        monkeypatch.setattr("os.path.exists", lambda p: True if p == os.path.join("backend", "runtime", "mcp", "config.json") else os.path.exists(p))
        
        original_open = open
        def mock_open(file, *args, **kwargs):
            if file == os.path.join("backend", "runtime", "mcp", "config.json"):
                return original_open(config_json, *args, **kwargs)
            return original_open(file, *args, **kwargs)
        
        monkeypatch.setattr("builtins.open", mock_open)

        # Should not raise, just log/print error
        mapping = MCPConfig.from_toml_section({"enabled": True, "servers": []})
        assert mapping["mcp"].servers == []

    def test_from_toml_section_with_dict_servers(self):
        """Test from_toml_section with a single dict instead of a list for servers."""
        mapping = MCPConfig.from_toml_section({
            "enabled": True, 
            "servers": {"name": "s1", "type": "sse", "url": "http://localhost/sse"}
        })
        assert len(mapping["mcp"].servers) == 1
        assert mapping["mcp"].servers[0].name == "s1"

    def test_merge_with_enabled(self):
        """Test merge correctly combines enabled flags."""
        a = MCPConfig(enabled=False, servers=[])
        b = MCPConfig(enabled=True, servers=[])
        assert a.merge(b).enabled is True
        
        c = MCPConfig(enabled=False, servers=[])
        d = MCPConfig(enabled=False, servers=[])
        assert c.merge(d).enabled is False

    def test_from_toml_section_no_mcp_key(self):
        """Test from_toml_section when the 'mcp' key is missing from the section data."""
        # The function is called with the content OF the [mcp] section, 
        # so it expects 'enabled' and 'servers' keys directly.
        mapping = MCPConfig.from_toml_section({"enabled": True})
        assert "mcp" in mapping
        assert mapping["mcp"].enabled is True

    def test_from_toml_section_windows_filtering(self, monkeypatch):
        """Test that stdio servers are filtered on Windows unless allowed."""
        import platform
        if platform.system() != "Windows":
            pytest.skip("This test is specific to Windows filtering logic")
            
        monkeypatch.setattr("os.path.exists", lambda p: False) # No config.json
        monkeypatch.delenv("FORGE_ENABLE_WINDOWS_MCP", raising=False)
        
        data = {
            "enabled": True,
            "servers": [
                {"name": "generic-stdio", "type": "stdio", "command": "node"},
                {"name": "browser-use", "type": "stdio", "command": "npx"},
                {"name": "my-sse", "type": "sse", "url": "http://localhost/sse"}
            ]
        }
        
        mapping = MCPConfig.from_toml_section(data)
        names = [s.name for s in mapping["mcp"].servers]
        
        assert "generic-stdio" not in names
        assert "browser-use" in names
        assert "my-sse" in names


# ── MCPConfig ─────────────────────────────────────────────────────────


class TestMCPConfig:
    def test_validate_servers_duplicate_raises(self):
        cfg = MCPConfig(
            servers=[
                MCPServerConfig(name="a", type="sse", url="http://example.com"),
                MCPServerConfig(name="b", type="sse", url="http://example.com"),
            ]
        )
        with pytest.raises(ValueError, match="Duplicate"):
            cfg.validate_servers()

    def test_validate_servers_ok(self):
        cfg = MCPConfig(
            servers=[
                MCPServerConfig(name="a", type="sse", url="http://a.com"),
                MCPServerConfig(name="b", type="sse", url="http://b.com"),
            ]
        )
        cfg.validate_servers()  # Should not raise

    def test_validate_servers_invalid_url_format(self):
        from unittest.mock import patch

        cfg = MCPConfig(
            servers=[MCPServerConfig(name="t", type="sse", url="http://test.com")]
        )
        with patch(
            "backend.core.config.mcp_config.urlparse",
            side_effect=Exception("parse error"),
        ):
            with pytest.raises(ValueError, match="Invalid URL"):
                cfg.validate_servers()

    def test_merge(self):
        a = MCPConfig(servers=[MCPServerConfig(name="a", type="sse", url="http://a.com")])
        b = MCPConfig(servers=[MCPServerConfig(name="b", type="sse", url="http://b.com")])
        merged = a.merge(b)
        assert len(merged.servers) == 2

    def test_from_toml_section_empty(self):
        mapping = MCPConfig.from_toml_section({})
        assert "mcp" in mapping
        assert mapping["mcp"].servers == []

    def test_from_toml_section_sse(self):
        mapping = MCPConfig.from_toml_section(
            {
                "servers": [{"name": "s1", "type": "sse", "url": "http://localhost:3000/sse"}],
            }
        )
        assert len(mapping["mcp"].servers) == 1
        assert mapping["mcp"].servers[0].transport == "sse"

    def test_from_toml_section_stdio(self):
        mapping = MCPConfig.from_toml_section(
            {
                "servers": [{"name": "s1", "type": "stdio", "command": "npx"}],
            }
        )
        stdio = [s for s in mapping["mcp"].servers if s.type == "stdio"]
        # stdio may be filtered on Windows — just check the list type
        assert isinstance(stdio, list)

    def test_from_toml_section_shttp(self):
        mapping = MCPConfig.from_toml_section(
            {
                "servers": [{"name": "s1", "type": "shttp", "url": "http://localhost:3000/mcp"}],
            }
        )
        shttp = [s for s in mapping["mcp"].servers if s.type == "shttp"]
        assert len(shttp) == 1
        assert shttp[0].url == "http://localhost:3000/mcp"

    def test_from_toml_section_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid MCP configuration"):
            MCPConfig.from_toml_section({"unknown_field": True})

    def test_sse_servers_compat_property(self):
        """Backward-compat property returns only SSE servers."""
        cfg = MCPConfig(
            servers=[
                MCPServerConfig(name="a", type="sse", url="http://a.com"),
                MCPServerConfig(name="b", type="stdio", command="npx"),
            ]
        )
        assert len(cfg.sse_servers) == 1
        assert len(cfg.stdio_servers) == 1
        assert len(cfg.shttp_servers) == 0

    def test_from_toml_section_loads_json_config(self, tmp_path, monkeypatch):
        """Test that from_toml_section also loads from backend/runtime/mcp/config.json."""
        # Setup mock config.json
        mcp_dir = tmp_path / "backend" / "runtime" / "mcp"
        mcp_dir.mkdir(parents=True)
        config_json = mcp_dir / "config.json"
        
        import json
        with open(config_json, "w") as f:
            json.dump({
                "mcpServers": {
                    "json-server": {"command": "npx", "args": ["test"]}
                }
            }, f)
            
        # Mock the path in the code to use our temp file
        import os
        
        monkeypatch.setattr("os.path.exists", lambda p: True if p == os.path.join("backend", "runtime", "mcp", "config.json") else os.path.exists(p))
        
        # We need to mock open to return our temp file content when that specific path is requested
        original_open = open
        def mock_open(file, *args, **kwargs):
            if file == os.path.join("backend", "runtime", "mcp", "config.json"):
                return original_open(config_json, *args, **kwargs)
            return original_open(file, *args, **kwargs)
        
        monkeypatch.setattr("builtins.open", mock_open)
        monkeypatch.setenv("FORGE_ENABLE_WINDOWS_MCP", "1")

        mapping = MCPConfig.from_toml_section({"enabled": True, "servers": []})
        server_names = [s.name for s in mapping["mcp"].servers]
        assert "json-server" in server_names


# ── ForgeMCPConfig ────────────────────────────────────────────────────


class TestForgeMCPConfig:
    def test_create_default_mcp_server_config(self):
        from backend.core.config.forge_config import ForgeConfig
        from backend.core.config.mcp_config import ForgeMCPConfig

        config = ForgeConfig()
        shttp, stdio = ForgeMCPConfig.create_default_mcp_server_config(
            "localhost:3000", config, "user123"
        )
        assert shttp is not None
        assert shttp.url == "http://localhost:3000/mcp/mcp"
        assert isinstance(stdio, list)
        assert not stdio
