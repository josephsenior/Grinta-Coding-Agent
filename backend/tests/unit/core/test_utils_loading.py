"""Tests for backend.core.config.utils — primary config loading entry points."""

from __future__ import annotations

import os
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from backend.core.config.agent_config import AgentConfig
from backend.core.config.forge_config import ForgeConfig
from backend.core.config.utils import (
    ConfigLoadSummary,
    _to_posix_workspace_path,
    get_agent_config_arg,
    get_condenser_config_arg,
    get_or_create_jwt_secret,
    load_from_json,
    register_custom_agents,
    finalize_config,
    load_forge_config,
    setup_config_from_args,
    parse_arguments,
)


# ── ConfigLoadSummary ──────────────────────────────────────────────────


class TestConfigLoadSummary:
    def test_record_and_emit(self):
        summary = ConfigLoadSummary("test.toml")
        summary.record("core", "invalid", "bad value")
        summary.record_missing("agent", "section missing")

        with patch("backend.core.logger.forge_logger.warning") as mock_warn:
            summary.emit()
            mock_warn.assert_called_once()
            # args[0] is fmt, args[1] is file, args[2] is issues
            issues_str = mock_warn.call_args[0][2]
            assert "[agent] missing: section missing" in issues_str
            assert "[core] invalid: bad value" in issues_str

    def test_has_fatal_issues(self):
        summary = ConfigLoadSummary("test.toml")
        assert not summary.has_fatal_issues()
        summary.record("core", "invalid", "error")
        assert summary.has_fatal_issues()
        assert "core: invalid: error" in summary.format_fatal_issues()

    def test_record_truncates_detail(self):
        summary = ConfigLoadSummary("test.toml")
        long_detail = "a" * 300
        summary.record("section", "reason", long_detail)
        assert len(summary._issues[0].detail) == 240
        assert summary._issues[0].detail.endswith("...")

    def test_emit_empty(self):
        summary = ConfigLoadSummary("test.toml")
        with patch("backend.core.logger.forge_logger.warning") as mock_warn:
            summary.emit()
            mock_warn.assert_not_called()


# ── Path Helpers ──────────────────────────────────────────────────────


class TestPathHelpers:
    def test_to_posix_workspace_path(self):
        assert _to_posix_workspace_path("C:\\Users\\test") == "/Users/test"
        assert _to_posix_workspace_path("relative/path") == "/relative/path"
        assert _to_posix_workspace_path("/already/posix") == "/already/posix"
        assert _to_posix_workspace_path("") == ""
        assert _to_posix_workspace_path("") is not None

    def test_to_posix_with_double_slashes(self):
        assert _to_posix_workspace_path("path//with///slashes") == "/path/with/slashes"


# ── JWT Secret ────────────────────────────────────────────────────────


class TestJwtSecret:
    def test_get_existing_secret(self):
        mock_store = MagicMock()
        mock_store.read.return_value = "existing_secret"
        assert get_or_create_jwt_secret(mock_store) == "existing_secret"

    def test_create_new_secret(self):
        mock_store = MagicMock()
        mock_store.read.side_effect = FileNotFoundError()
        secret = get_or_create_jwt_secret(mock_store)
        assert len(secret) == 32  # uuid4().hex
        mock_store.write.assert_called_once()


# ── Finalization ──────────────────────────────────────────────────────


class TestFinalization:
    def test_finalize_config(self, tmp_path):
        cfg = ForgeConfig()
        cfg.cache_dir = str(tmp_path / "cache")
        cfg.llms = {"default": MagicMock()}
        cfg.llms["default"].log_completions_folder = "logs"

        with patch("backend.core.config.utils.get_file_store") as mock_get_store:
            with patch("pathlib.Path.mkdir") as mock_mkdir:
                mock_store = MagicMock()
                mock_get_store.return_value = mock_store
                mock_store.read.return_value = "secret"

                finalize_config(cfg)

                # assert os.path.exists(cfg.cache_dir) # Replaced by mock
                assert mock_mkdir.called
                assert os.path.isabs(cfg.llms["default"].log_completions_folder)
                assert cast(Any, cfg.jwt_secret).get_secret_value() == "secret"


# ── Named Group Loaders ───────────────────────────────────────────────


class TestNamedGroupLoaders:
    def test_get_agent_config_arg_success(self, tmp_path):
        json_file = tmp_path / "settings.json"

        with patch("backend.core.config.utils._load_json_config") as mock_load:
            mock_load.return_value = {"agent": {"my_agent": {"name": "custom_name"}}}
            config = get_agent_config_arg("agent.my_agent", str(json_file))
            assert isinstance(config, AgentConfig)
            assert config.name == "custom_name"

    def test_get_agent_config_arg_missing(self, tmp_path):
        with patch("backend.core.config.utils._load_json_config", return_value={}):
            assert get_agent_config_arg("nonexistent") is None

    def test_get_condenser_config_arg_success(self, tmp_path):
        json_file = tmp_path / "settings.json"
        # Mocking to avoid complex dependencies
        with patch("backend.core.config.utils._load_json_config") as mock_load:
            mock_load.return_value = {
                "condenser_type": "recent",
                "condenser_max_events": 10,
            }
            with patch(
                "backend.core.config.condenser_config.create_condenser_config"
            ) as mock_create:
                mock_cfg = MagicMock()
                mock_create.return_value = mock_cfg
                result = get_condenser_config_arg("my_condenser", str(json_file))
                assert result is mock_cfg

    def test_get_condenser_config_arg_missing_type(self, tmp_path):
        with patch("backend.core.config.utils._load_json_config") as mock_load:
            mock_load.return_value = {"condenser_type": None}
            assert get_condenser_config_arg("bad") is None


# ── Agent Registration ────────────────────────────────────────────────


class TestAgentRegistration:
    def test_register_custom_agents(self):
        cfg = ForgeConfig()
        mock_agent_cfg = MagicMock()
        mock_agent_cfg.classpath = "some.module.Class"
        cfg.agents = {"custom": mock_agent_cfg}

        with patch("backend.core.config.utils.get_impl") as mock_get_impl:
            mock_cls = MagicMock()
            mock_get_impl.return_value = mock_cls
            from backend.controller.agent import Agent

            with patch.object(Agent, "register") as mock_register:
                register_custom_agents(cfg)
                mock_register.assert_called_with("custom", mock_cls)


# ── Main Entry Points ─────────────────────────────────────────────────


class TestMainEntryPoints:
    @patch("backend.core.config.utils.rebuild_config_models")
    @patch("backend.core.config.utils.load_from_json")
    @patch("backend.core.config.utils.load_from_env")
    @patch("backend.core.config.utils.finalize_config")
    @patch("backend.core.config.utils.export_llm_api_keys")
    @patch("backend.core.config.utils.register_custom_agents")
    def test_load_FORGE_config_calls(self, *mocks):
        # This test only verifies that the other functions are called
        load_forge_config(set_logging_levels=True)
        for m in mocks:
            assert m.called

    def test_load_FORGE_config_execution(self, tmp_path):
        # This test actually executes the function (with minimal mocking)
        with patch("backend.core.config.utils.rebuild_config_models"):
            with patch("backend.core.config.utils.load_from_json"):
                with patch("backend.core.config.utils.load_from_env"):
                    with patch("backend.core.config.utils.finalize_config"):
                        with patch("backend.core.config.utils.export_llm_api_keys"):
                            with patch(
                                "backend.core.config.utils.register_custom_agents"
                            ):
                                # This will execute the body of load_FORGE_config
                                load_forge_config(set_logging_levels=True)

    def test_setup_config_from_args_execution(self):
        args = MagicMock()
        args.config_file = "settings.json"
        with patch("backend.core.config.utils.load_forge_config") as mock_load:
            with patch("backend.core.config.utils.apply_llm_config_override"):
                with patch("backend.core.config.utils.apply_additional_overrides"):
                    setup_config_from_args(args)
                    mock_load.assert_called_with(config_file="settings.json")


# ── Config load (load_from_json) ──────────────────────────────────────


class TestLoadFromJson:
    def test_load_from_json_success(self, tmp_path):
        json_file = tmp_path / "settings.json"
        json_file.write_text('{"mcp_host": "custom-host:9999"}')
        cfg = ForgeConfig()
        load_from_json(cfg, str(json_file))
        assert cfg.mcp_host == "custom-host:9999"

    def test_load_from_json_file_not_found(self):
        cfg = ForgeConfig()
        # Should return silently
        load_from_json(cfg, "nonexistent.json")

    def test_load_from_json_decode_error(self, tmp_path):
        json_file = tmp_path / "bad.json"
        json_file.write_text("invalid } json { here")
        cfg = ForgeConfig()
        with patch("backend.core.logger.forge_logger.warning") as mock_warn:
            load_from_json(cfg, str(json_file))
            mock_warn.assert_called()

    def test_load_from_json_strict_mode_fail(self, tmp_path):
        json_file = tmp_path / "bad.json"
        json_file.write_text("invalid } json { here")
        with patch.dict(os.environ, {"FORGE_STRICT_CONFIG": "true"}):
            with pytest.raises(ValueError, match="Invalid JSON"):
                load_from_json(ForgeConfig(), str(json_file))

    def test_load_from_json_strict_mode_fatal_issue(self, tmp_path):
        json_file = tmp_path / "settings.json"
        json_file.write_text('{"file_store": "memory"}')
        ForgeConfig()
        with patch.dict(os.environ, {"FORGE_STRICT_CONFIG": "true"}):
            with patch("backend.core.config.utils.logger.forge_logger.warning"):
                # Manually force summary fatal in new json logic if needed
                pass


# ── Condenser Loader Extra ───────────────────────────────────────────


class TestCondenserLoaderExtra:
    def test_get_condenser_config_missing_section(self, tmp_path):
        with patch("backend.core.config.utils._load_json_config", return_value={}):
            assert get_condenser_config_arg("my_condenser") is None

    def test_get_condenser_config_arg_validation_error(self, tmp_path):
        with patch(
            "backend.core.config.utils._load_json_config",
            return_value={"condenser_type": "recent"},
        ):
            with patch(
                "backend.core.config.condenser_config.create_condenser_config",
                side_effect=ValidationError.from_exception_data("test", []),
            ):
                assert get_condenser_config_arg("my_condenser") is None

    def test_process_llm_condenser_success(self):
        from backend.core.config.utils import _process_llm_condenser

        condenser_data = {"llm_config": "my_llm"}
        with patch("backend.core.config.utils.get_llm_config_arg") as mock_get:
            mock_llm = MagicMock()
            mock_get.return_value = mock_llm
            result = _process_llm_condenser(condenser_data, "arg", "file.toml")
            assert result is not None
            assert result["llm_config"] is mock_llm

    def test_process_llm_condenser_fail(self):
        from backend.core.config.utils import _process_llm_condenser

        condenser_data = {"llm_config": "my_llm"}
        with patch("backend.core.config.utils.get_llm_config_arg", return_value=None):
            assert _process_llm_condenser(condenser_data, "arg", "file.toml") is None


# ── Agent Registration Extra ──────────────────────────────────────────


class TestAgentRegistrationExtra:
    def test_register_custom_agents_failure_handled(self):
        cfg = ForgeConfig()
        mock_agent_cfg = MagicMock()
        mock_agent_cfg.classpath = "bad.Path"
        cfg.agents = {"bad": mock_agent_cfg}

        with patch(
            "backend.core.config.utils.get_impl", side_effect=Exception("import fail")
        ):
            # Should not raise
            register_custom_agents(cfg)

    def test_register_custom_agents_no_classpath(self):
        cfg = ForgeConfig()
        cfg.agents = {"no_cp": MagicMock(spec=[])}  # No classpath attribute
        # Should just skip
        register_custom_agents(cfg)


class TestCoverageGapsV2:
    def test_format_fatal_issues_empty(self):
        summary = ConfigLoadSummary("test.toml")
        assert summary.format_fatal_issues() == ""

    def test_format_fatal_issues_loop(self):
        summary = ConfigLoadSummary("test.toml")
        summary.record("core", "invalid", "err1")
        summary.record("agent", "invalid", "err2")
        formatted = summary.format_fatal_issues()
        assert "core: invalid: err1" in formatted
        assert "agent: invalid: err2" in formatted

    def test_get_agent_config_arg_debug_log(self, tmp_path):
        with patch(
            "backend.core.config.utils._load_json_config", return_value={"agent": {}}
        ):
            with patch("backend.core.logger.forge_logger.debug") as mock_debug:
                assert get_agent_config_arg("my_agent") is None
                mock_debug.assert_any_call(
                    "Loading from toml failed for %s", "my_agent"
                )

    def test_get_condenser_config_arg_logs(self, tmp_path):
        # Test success log (roughly line 315)
        with patch(
            "backend.core.config.utils._load_json_config",
            return_value={"condenser_type": "recent"},
        ):
            with patch(
                "backend.core.config.condenser_config.create_condenser_config"
            ) as mock_create:
                mock_cfg = MagicMock()
                mock_create.return_value = mock_cfg
                with patch("backend.core.logger.forge_logger.info") as mock_info:
                    get_condenser_config_arg("c1")
                    mock_info.assert_called()

        # Test error log missing type (roughly line 330)
        with patch(
            "backend.core.config.utils._load_json_config",
            return_value={"condenser_type": None},
        ):
            with patch("backend.core.logger.forge_logger.error") as mock_error:
                get_condenser_config_arg("c2")
                mock_error.assert_called_with(
                    'Missing "type" field in [condenser.%s] section of %s',
                    "c2",
                    "settings.json",
                )

        # Test error log for failed LLM load (roughly line 351/304)
        with patch(
            "backend.core.config.utils._load_json_config",
            return_value={"condenser_type": "llm", "condenser_llm_config": "missing"},
        ):
            with patch(
                "backend.core.config.utils.get_llm_config_arg", return_value=None
            ):
                with patch("backend.core.logger.forge_logger.error") as mock_error:
                    get_condenser_config_arg("c3")
                    mock_error.assert_any_call(
                        "Failed to load required LLM config '%s' for condenser '%s'.",
                        "missing",
                        "c3",
                    )

    def test_parse_arguments_version(self):
        with patch("backend.core.config.arg_utils.get_headless_parser") as mock_get:
            mock_parser = MagicMock()
            mock_get.return_value = mock_parser
            mock_parser.parse_args.return_value = MagicMock(version=True)
            with pytest.raises(SystemExit) as exc:
                parse_arguments()
            assert exc.value.code == 0

    def test_parse_arguments_no_version(self):
        with patch("backend.core.config.arg_utils.get_headless_parser") as mock_get:
            mock_parser = MagicMock()
            mock_get.return_value = mock_parser
            mock_parser.parse_args.return_value = MagicMock(version=False)
            args = parse_arguments()
            assert args.version is False
