"""Tests for backend.core.schemas.metadata — CmdOutputMetadataSchema and ToolCallMetadataSchema."""

from __future__ import annotations

import pytest

from backend.core.constants import DEFAULT_CMD_EXIT_CODE, DEFAULT_CMD_PID
from backend.core.schemas.metadata import (
    CmdOutputMetadataSchema,
    ToolCallMetadataSchema,
)


# ── CmdOutputMetadataSchema ─────────────────────────────────────────


class TestCmdOutputMetadataSchema:
    def test_defaults(self):
        m = CmdOutputMetadataSchema()
        assert m.exit_code == DEFAULT_CMD_EXIT_CODE
        assert m.pid == DEFAULT_CMD_PID
        assert m.username is None
        assert m.hostname is None
        assert m.working_dir is None
        assert m.py_interpreter_path is None
        assert m.prefix == ""
        assert m.suffix == ""

    def test_custom_values(self):
        m = CmdOutputMetadataSchema(
            exit_code=0,
            pid=1234,
            username="user",
            hostname="host",
            working_dir="/home/user",
            py_interpreter_path="/usr/bin/python3",
            prefix="[PRE]",
            suffix="[POST]",
        )
        assert m.exit_code == 0
        assert m.pid == 1234
        assert m.username == "user"
        assert m.hostname == "host"
        assert m.working_dir == "/home/user"
        assert m.py_interpreter_path == "/usr/bin/python3"
        assert m.prefix == "[PRE]"
        assert m.suffix == "[POST]"

    def test_empty_username_rejected(self):
        with pytest.raises(Exception):
            CmdOutputMetadataSchema(username="")

    def test_empty_hostname_rejected(self):
        with pytest.raises(Exception):
            CmdOutputMetadataSchema(hostname="")

    def test_empty_working_dir_rejected(self):
        with pytest.raises(Exception):
            CmdOutputMetadataSchema(working_dir="")

    def test_none_optional_strings_ok(self):
        m = CmdOutputMetadataSchema(
            username=None, hostname=None, working_dir=None, py_interpreter_path=None
        )
        assert m.username is None


# ── ToolCallMetadataSchema ───────────────────────────────────────────


class TestToolCallMetadataSchema:
    def test_valid(self):
        m = ToolCallMetadataSchema(
            function_name="run_command",
            tool_call_id="tc_001",
            total_calls_in_response=1,
        )
        assert m.function_name == "run_command"
        assert m.tool_call_id == "tc_001"
        assert m.model_response is None
        assert m.total_calls_in_response == 1

    def test_with_model_response(self):
        m = ToolCallMetadataSchema(
            function_name="edit_file",
            tool_call_id="tc_002",
            total_calls_in_response=2,
            model_response={"id": "resp_1"},
        )
        assert m.model_response == {"id": "resp_1"}

    def test_empty_function_name_rejected(self):
        with pytest.raises(Exception):
            ToolCallMetadataSchema(
                function_name="",
                tool_call_id="tc",
                total_calls_in_response=1,
            )

    def test_empty_tool_call_id_rejected(self):
        with pytest.raises(Exception):
            ToolCallMetadataSchema(
                function_name="fn",
                tool_call_id="",
                total_calls_in_response=1,
            )

    def test_total_calls_ge_1(self):
        with pytest.raises(Exception):
            ToolCallMetadataSchema(
                function_name="fn",
                tool_call_id="tc",
                total_calls_in_response=0,
            )

    def test_total_calls_valid(self):
        m = ToolCallMetadataSchema(
            function_name="fn",
            tool_call_id="tc",
            total_calls_in_response=5,
        )
        assert m.total_calls_in_response == 5
