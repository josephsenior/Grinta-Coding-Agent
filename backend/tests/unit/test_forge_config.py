"""Tests for backend.core.config.forge_config — ForgeConfig model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core.config.agent_config import AgentConfig
from backend.core.config.forge_config import (
    EventStreamConfig,
    FileUploadsConfig,
    ForgeConfig,
    GitIdentityConfig,
    TrajectoryConfig,
)
from backend.core.config.llm_config import LLMConfig


# ── Sub-models ───────────────────────────────────────────────────────


class TestGitIdentityConfig:
    def test_defaults(self):
        g = GitIdentityConfig()
        assert isinstance(g.user_name, str)
        assert isinstance(g.user_email, str)
        assert g.init_in_empty_workspace is False


class TestFileUploadsConfig:
    def test_defaults(self):
        f = FileUploadsConfig()
        assert f.max_file_size_mb > 0
        assert f.restrict_file_types is False
        assert f.allowed_extensions == set()


class TestTrajectoryConfig:
    def test_defaults(self):
        t = TrajectoryConfig()
        assert t.replay_path is None
        assert t.save_path is None
        assert t.save_screenshots is False


class TestEventStreamConfig:
    def test_defaults(self):
        e = EventStreamConfig()
        assert e.max_queue_size == 2000
        assert e.drop_policy == "drop_oldest"
        assert 0 < e.hwm_ratio < 1.0
        assert e.workers > 0
        assert e.async_write is False


# ── ForgeConfig defaults ─────────────────────────────────────────────


class TestForgeConfigDefaults:
    def test_default_runtime(self):
        cfg = ForgeConfig()
        assert isinstance(cfg.runtime, str)

    def test_default_file_store(self):
        cfg = ForgeConfig()
        assert isinstance(cfg.file_store, str)

    def test_default_max_iterations(self):
        cfg = ForgeConfig()
        assert cfg.max_iterations > 0

    def test_default_max_budget(self):
        cfg = ForgeConfig()
        assert cfg.max_budget_per_task == 5.0

    def test_default_debug(self):
        cfg = ForgeConfig()
        assert cfg.debug is False

    def test_default_disable_color(self):
        cfg = ForgeConfig()
        assert cfg.disable_color is False

    def test_jwt_secret_default_none(self):
        cfg = ForgeConfig()
        assert cfg.jwt_secret is None


# ── LLM config management ───────────────────────────────────────────


class TestForgeConfigLlm:
    def test_get_llm_config_default(self):
        cfg = ForgeConfig()
        llm = cfg.get_llm_config()
        assert isinstance(llm, LLMConfig)

    def test_get_llm_config_named(self):
        cfg = ForgeConfig()
        custom = LLMConfig(model="gpt-4")
        cfg.set_llm_config(custom, name="custom")
        assert cfg.get_llm_config("custom").model == "gpt-4"

    def test_get_llm_config_missing_falls_back(self):
        cfg = ForgeConfig()
        llm = cfg.get_llm_config("nonexistent")
        assert isinstance(llm, LLMConfig)

    def test_set_llm_config(self):
        cfg = ForgeConfig()
        llm = LLMConfig(model="test-model")
        cfg.set_llm_config(llm)
        assert cfg.get_llm_config().model == "test-model"


# ── Agent config management ─────────────────────────────────────────


class TestForgeConfigAgent:
    def test_get_agent_config_default(self):
        cfg = ForgeConfig()
        agent = cfg.get_agent_config()
        assert isinstance(agent, AgentConfig)

    def test_set_agent_config(self):
        cfg = ForgeConfig()
        agent = AgentConfig(name="MyAgent")
        cfg.set_agent_config(agent, name="my_agent")
        assert cfg.get_agent_config("my_agent").name == "MyAgent"

    def test_get_agent_configs(self):
        cfg = ForgeConfig()
        cfg.set_agent_config(AgentConfig(name="A"), name="a")
        cfg.set_agent_config(AgentConfig(name="B"), name="b")
        configs = cfg.get_agent_configs()
        assert "a" in configs
        assert "b" in configs

    def test_get_agent_to_llm_config_map(self):
        cfg = ForgeConfig()
        cfg.set_agent_config(AgentConfig(name="agent1"), name="agent1")
        mapping = cfg.get_agent_to_llm_config_map()
        assert "agent1" in mapping
        assert isinstance(mapping["agent1"], LLMConfig)


# ── Post init sync ──────────────────────────────────────────────────


class TestForgeConfigPostInit:
    def test_git_identity_synced(self):
        cfg = ForgeConfig(vcs_user_name="TestUser", vcs_user_email="test@test.com")
        assert cfg.git.user_name == "TestUser"
        assert cfg.git.user_email == "test@test.com"

    def test_file_uploads_synced(self):
        cfg = ForgeConfig(file_uploads_max_file_size_mb=50)
        assert cfg.file_uploads.max_file_size_mb == 50

    def test_trajectory_synced(self):
        cfg = ForgeConfig(replay_trajectory_path="/tmp/replay.json")
        assert cfg.trajectory.replay_path == "/tmp/replay.json"

    def test_git_init_synced(self):
        cfg = ForgeConfig(init_git_in_empty_workspace=True)
        assert cfg.git.init_in_empty_workspace is True


# ── Validation ───────────────────────────────────────────────────────


class TestForgeConfigValidation:
    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            ForgeConfig(totally_fake_field="value")


# ── get_llm_config_from_agent ────────────────────────────────────────


class TestGetLlmConfigFromAgent:
    def test_default_agent(self):
        cfg = ForgeConfig()
        llm = cfg.get_llm_config_from_agent()
        assert isinstance(llm, LLMConfig)

    def test_agent_with_llm_config(self):
        cfg = ForgeConfig()
        llm = LLMConfig(model="agent-model")
        agent = AgentConfig(name="special", llm_config=llm)
        cfg.set_agent_config(agent, name="special")
        result = cfg.get_llm_config_from_agent("special")
        assert result.model == "agent-model"
