"""Tests for backend.core.config.arg_utils — CLI argument parsers."""

from __future__ import annotations

import argparse

import pytest

from backend.core.config.arg_utils import (
    add_common_arguments,
    add_headless_specific_arguments,
    get_cli_parser,
    get_headless_parser,
    get_subparser,
)


# ── get_subparser ────────────────────────────────────────────────────


class TestGetSubparser:
    def test_found(self):
        parser = get_cli_parser()
        sub = get_subparser(parser, "serve")
        assert isinstance(sub, argparse.ArgumentParser)

    def test_init_subparser(self):
        parser = get_cli_parser()
        sub = get_subparser(parser, "init")
        assert isinstance(sub, argparse.ArgumentParser)

    def test_health_subparser(self):
        parser = get_cli_parser()
        sub = get_subparser(parser, "health")
        assert isinstance(sub, argparse.ArgumentParser)

    def test_not_found_raises(self):
        parser = get_cli_parser()
        with pytest.raises(ValueError, match="not found"):
            get_subparser(parser, "nonexistent")

    def test_empty_parser(self):
        parser = argparse.ArgumentParser()
        with pytest.raises(ValueError, match="not found"):
            get_subparser(parser, "anything")


# ── add_common_arguments ─────────────────────────────────────────────


class TestAddCommonArguments:
    def _make_parser(self):
        p = argparse.ArgumentParser()
        add_common_arguments(p)
        return p

    def test_defaults(self):
        p = self._make_parser()
        args = p.parse_args([])
        assert args.task == ""
        assert args.file is None
        assert args.name == ""
        assert args.log_level is None
        assert args.llm_config is None
        assert args.agent_config is None
        assert args.version is False

    def test_task(self):
        p = self._make_parser()
        args = p.parse_args(["-t", "do stuff"])
        assert args.task == "do stuff"
        args2 = p.parse_args(["--task", "other"])
        assert args2.task == "other"

    def test_file(self):
        p = self._make_parser()
        args = p.parse_args(["-f", "path.txt"])
        assert args.file == "path.txt"

    def test_version_flag(self):
        p = self._make_parser()
        args = p.parse_args(["-v"])
        assert args.version is True

    def test_llm_config(self):
        p = self._make_parser()
        args = p.parse_args(["-l", "llama3"])
        assert args.llm_config == "llama3"

    def test_agent_config(self):
        p = self._make_parser()
        args = p.parse_args(["--agent-config", "CodeAct"])
        assert args.agent_config == "CodeAct"


# ── add_headless_specific_arguments ──────────────────────────────────


class TestAddHeadlessArguments:
    def _make_parser(self):
        p = argparse.ArgumentParser()
        add_headless_specific_arguments(p)
        return p

    def test_defaults(self):
        p = self._make_parser()
        args = p.parse_args([])
        assert args.directory is None
        assert args.agent_cls is None
        assert args.max_iterations is None
        assert args.max_budget_per_task is None
        assert args.no_auto_continue is False
        assert args.selected_repo is None

    def test_directory(self):
        p = self._make_parser()
        args = p.parse_args(["-d", "/tmp/work"])
        assert args.directory == "/tmp/work"

    def test_max_iterations(self):
        p = self._make_parser()
        args = p.parse_args(["-i", "50"])
        assert args.max_iterations == 50

    def test_max_budget(self):
        p = self._make_parser()
        args = p.parse_args(["-b", "5.5"])
        assert args.max_budget_per_task == 5.5

    def test_no_auto_continue(self):
        p = self._make_parser()
        args = p.parse_args(["--no-auto-continue"])
        assert args.no_auto_continue is True

    def test_selected_repo(self):
        p = self._make_parser()
        args = p.parse_args(["--selected-repo", "owner/repo"])
        assert args.selected_repo == "owner/repo"


# ── get_cli_parser ───────────────────────────────────────────────────


class TestGetCliParser:
    def test_returns_parser(self):
        p = get_cli_parser()
        assert isinstance(p, argparse.ArgumentParser)

    def test_serve_command(self):
        p = get_cli_parser()
        args = p.parse_args(["serve"])
        assert args.command == "serve"

    def test_init_command(self):
        p = get_cli_parser()
        args = p.parse_args(["init", "myproject"])
        assert args.command == "init"
        assert args.project_name == "myproject"

    def test_init_default_template(self):
        p = get_cli_parser()
        args = p.parse_args(["init"])
        assert args.template == "basic"
        assert args.project_name is None

    def test_init_custom_template(self):
        p = get_cli_parser()
        args = p.parse_args(["init", "--template", "advanced"])
        assert args.template == "advanced"

    def test_conversation_arg(self):
        p = get_cli_parser()
        args = p.parse_args(["--conversation", "conv-123"])
        assert args.conversation == "conv-123"

    def test_no_command(self):
        p = get_cli_parser()
        args = p.parse_args([])
        assert args.command is None


# ── get_headless_parser ──────────────────────────────────────────────


class TestGetHeadlessParser:
    def test_returns_parser(self):
        p = get_headless_parser()
        assert isinstance(p, argparse.ArgumentParser)

    def test_has_common_and_headless_args(self):
        p = get_headless_parser()
        args = p.parse_args(["-t", "task", "-d", "/work", "-i", "10"])
        assert args.task == "task"
        assert args.directory == "/work"
        assert args.max_iterations == 10
