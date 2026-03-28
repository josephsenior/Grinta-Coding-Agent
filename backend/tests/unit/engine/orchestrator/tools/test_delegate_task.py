from __future__ import annotations

import pytest

from backend.ledger.action.agent import DelegateTaskAction
from backend.ledger.observation.agent import DelegateTaskObservation
from backend.core.errors import FunctionCallValidationError
from backend.engine.tools.delegate_task import (
    create_delegate_task_tool,
    build_delegate_task_action,
)


def test_delegate_task_schema():
    """Test that the delegate_task schema matches expected format."""
    schema = create_delegate_task_tool()
    assert schema["function"]["name"] == "delegate_task"
    assert "task_description" in schema["function"]["parameters"]["properties"]
    assert "files" in schema["function"]["parameters"]["properties"]


def test_build_delegate_task_action_valid():
    """Test building a DelegateTaskAction from valid dictionary."""
    args = {"task_description": "Fix bug in foo.py", "files": ["foo.py", "bar.py"]}
    action = build_delegate_task_action(args)
    assert isinstance(action, DelegateTaskAction)
    assert action.task_description == "Fix bug in foo.py"
    assert action.files == ["foo.py", "bar.py"]


def test_build_delegate_task_action_invalid():
    """Test building a DelegateTaskAction with missing required args."""
    args = {"files": ["foo.py"]}
    with pytest.raises(FunctionCallValidationError):
        build_delegate_task_action(args)


def test_delegate_task_observation():
    """Test the DelegateTaskObservation properties."""
    obs1 = DelegateTaskObservation(
        success=True, content="Fixed the bug in 5 lines.", error_message=""
    )
    assert obs1.success is True
    assert "Fixed the bug" in obs1.content
    assert "completed" in obs1.message

    obs2 = DelegateTaskObservation(
        success=False, content="", error_message="Sub-agent crashed."
    )
    assert obs2.success is False
    assert "Sub-agent crashed" in obs2.error_message
    assert "failed" in obs2.message
