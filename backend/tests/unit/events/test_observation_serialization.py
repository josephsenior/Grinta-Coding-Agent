"""Tests for backend.events.serialization.observation."""

from __future__ import annotations

import pytest

from backend.events.observation import (
    CmdOutputObservation,
    ErrorObservation,
    FileReadObservation,
    MCPObservation,
)
from backend.events.serialization.observation import (
    observation_from_dict,
    _validate_observation_dict,
    _update_cmd_output_metadata,
    _process_recall_observation_data,
)
from backend.events.observation.commands import CmdOutputMetadata
from backend.core.enums import RecallType


# ── _validate_observation_dict ───────────────────────────────────────

class TestValidateObservationDict:
    def test_valid(self):
        _validate_observation_dict({"observation": "error"})

    def test_missing_key(self):
        with pytest.raises(KeyError, match="observation"):
            _validate_observation_dict({})


# ── _update_cmd_output_metadata ──────────────────────────────────────

class TestUpdateCmdOutputMetadata:
    def test_none_creates_new(self):
        result = _update_cmd_output_metadata(None, exit_code=0)
        assert isinstance(result, CmdOutputMetadata)
        assert result.exit_code == 0

    def test_dict_updates(self):
        meta = {"exit_code": -1}
        result = _update_cmd_output_metadata(meta, exit_code=0)
        assert result["exit_code"] == 0

    def test_instance_updates(self):
        meta = CmdOutputMetadata(exit_code=-1)
        result = _update_cmd_output_metadata(meta, exit_code=42)
        assert result.exit_code == 42


# ── _process_recall_observation_data ─────────────────────────────────

class TestProcessRecallData:
    def test_recall_type_string(self):
        extras = {"recall_type": "workspace_context"}
        _process_recall_observation_data(extras)
        assert extras["recall_type"] == RecallType.WORKSPACE_CONTEXT

    def test_no_recall_type(self):
        extras = {}
        _process_recall_observation_data(extras)
        assert "recall_type" not in extras


# ── observation_from_dict ────────────────────────────────────────────

class TestObservationFromDict:
    def test_error_observation(self):
        d = {"observation": "error", "content": "bad", "extras": {"error_id": "E1"}}
        obs = observation_from_dict(d)
        assert isinstance(obs, ErrorObservation)
        assert obs.content == "bad"

    def test_file_read_observation(self):
        d = {
            "observation": "read",
            "content": "file data",
            "extras": {"path": "/tmp/x.py"},
        }
        obs = observation_from_dict(d)
        assert isinstance(obs, FileReadObservation)

    def test_cmd_output_observation(self):
        # CmdOutputObservation.observation is an empty string in the registry
        d = {
            "observation": "",
            "content": "output",
            "extras": {"command": "ls", "command_id": 1},
        }
        obs = observation_from_dict(d)
        assert isinstance(obs, CmdOutputObservation)

    def test_mcp_observation(self):
        d = {"observation": "mcp", "content": "mcp result", "extras": {}}
        obs = observation_from_dict(d)
        assert isinstance(obs, MCPObservation)

    def test_unknown_type_raises(self):
        d = {"observation": "definitely_not_real"}
        with pytest.raises(KeyError):
            observation_from_dict(d)

    def test_missing_observation_key(self):
        with pytest.raises(KeyError):
            observation_from_dict({"content": "something"})
