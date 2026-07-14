from __future__ import annotations

from backend.execution.server.base import Runtime
from backend.ledger.action import CmdRunAction
from backend.ledger.observation import CmdOutputObservation


def test_nonzero_command_exit_is_never_serialized_as_success() -> None:
    action = CmdRunAction(command='pytest -q')
    observation = CmdOutputObservation(
        content='1 failed', command='pytest -q', exit_code=1
    )
    # Some command layers use ``ok`` to mean that invocation completed.  The
    # runtime must replace that with process success for terminal observations.
    observation.tool_result = {'ok': True, 'exit_code': 1}

    should_add = Runtime._process_observation(object(), observation, action)

    assert should_add is True
    assert observation.tool_result['ok'] is False
    assert observation.tool_result['exit_code'] == 1
