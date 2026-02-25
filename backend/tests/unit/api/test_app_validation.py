"""Tests for backend.api.app — config validation functions."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


# We test the individual validation functions, not the full app startup.
from backend.api.app import (
    _check_budget_sanity,
    _check_config_file_existence,
    _check_database_availability,
    _check_system_dependencies,
    _collect_validation_issues,
)


# ── _check_budget_sanity ─────────────────────────────────────────────


class TestCheckBudgetSanity:
    def test_no_budget_warns(self):
        warnings: list[str] = []
        with patch("backend.api.app._forge_config") as mock_cfg:
            mock_cfg.max_budget_per_task = None
            _check_budget_sanity(warnings)
        assert len(warnings) == 1
        assert "unlimited" in warnings[0].lower()

    def test_zero_budget_warns(self):
        warnings: list[str] = []
        with patch("backend.api.app._forge_config") as mock_cfg:
            mock_cfg.max_budget_per_task = 0
            _check_budget_sanity(warnings)
        assert len(warnings) == 1

    def test_valid_budget_no_warnings(self):
        warnings: list[str] = []
        with patch("backend.api.app._forge_config") as mock_cfg:
            mock_cfg.max_budget_per_task = 5.0
            _check_budget_sanity(warnings)
        assert not warnings


# ── _check_database_availability ─────────────────────────────────────


class TestCheckDatabaseAvailability:
    def test_file_storage_no_warnings(self):
        warnings: list[str] = []
        with patch.dict(os.environ, {"KB_STORAGE_TYPE": "file"}, clear=False):
            _check_database_availability(warnings)
        assert not warnings

    def test_database_without_asyncpg_warns(self):
        warnings: list[str] = []
        with (
            patch.dict(os.environ, {"KB_STORAGE_TYPE": "database"}, clear=False),
            patch("importlib.util.find_spec", return_value=None),
        ):
            _check_database_availability(warnings)
        assert any("asyncpg" in w for w in warnings)

    def test_database_without_url_warns(self):
        warnings: list[str] = []
        env = {"KB_STORAGE_TYPE": "database"}
        # Remove DATABASE_URL if present
        env_copy = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
        env_copy.update(env)
        with (
            patch.dict(os.environ, env_copy, clear=True),
            patch("importlib.util.find_spec", return_value=MagicMock()),
        ):
            _check_database_availability(warnings)
        assert any("DATABASE_URL" in w for w in warnings)


# ── _check_system_dependencies ───────────────────────────────────────


class TestCheckSystemDependencies:
    def test_tmux_missing_warns(self):
        warnings: list[str] = []
        with patch("shutil.which", return_value=None):
            _check_system_dependencies(warnings)
        assert len(warnings) == 1
        assert "tmux" in warnings[0].lower()

    def test_tmux_present_no_warnings(self):
        warnings: list[str] = []
        with patch("shutil.which", return_value="/usr/bin/tmux"):
            _check_system_dependencies(warnings)
        assert not warnings


# ── _check_config_file_existence ─────────────────────────────────────


class TestCheckConfigFileExistence:
    def test_missing_config_warns(self):
        warnings: list[str] = []
        with patch("pathlib.Path.exists", return_value=False):
            _check_config_file_existence(warnings)
        assert len(warnings) == 1
        assert "config.toml" in warnings[0]

    def test_existing_config_no_warnings(self):
        warnings: list[str] = []
        with patch("pathlib.Path.exists", return_value=True):
            _check_config_file_existence(warnings)
        assert not warnings


# ── _collect_validation_issues ───────────────────────────────────────


class TestCollectValidationIssues:
    def test_returns_tuple_of_lists(self):
        with (
            patch("backend.api.app._check_budget_sanity"),
            patch("backend.api.app._check_database_availability"),
            patch("backend.api.app._check_system_dependencies"),
            patch("backend.api.app._check_config_file_existence"),
        ):
            warnings, errors = _collect_validation_issues(strict=False)
        assert isinstance(warnings, list)
        assert isinstance(errors, list)
