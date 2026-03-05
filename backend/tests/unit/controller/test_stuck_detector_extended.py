"""Extended unit tests for StuckDetector covering repetition scores and advanced patterns."""

from __future__ import annotations
from typing import Any
from types import SimpleNamespace
from backend.controller.stuck import StuckDetector
from backend.events.action.commands import CmdRunAction
from backend.events.event import EventSource
from backend.events.observation.commands import CmdOutputObservation
from backend.events.observation.error import ErrorObservation

def _state(history: list) -> SimpleNamespace:
    return SimpleNamespace(history=history)

def _cmd(command: str = "ls") -> CmdRunAction:
    return CmdRunAction(command=command)

def _cmd_output(command: str = "ls", content: str = "file.txt", exit_code: int = 0) -> CmdOutputObservation:
    return CmdOutputObservation(content=content, command=command, exit_code=exit_code)

def _error(content: str = "something failed") -> ErrorObservation:
    return ErrorObservation(content=content)

class TestRepetitionScore:
    def test_score_zero_for_empty_history(self):
        sd = StuckDetector(_state([]))  # type: ignore[arg-type]
        assert sd.compute_repetition_score() == 0.0

    def test_score_for_repeating_actions(self):
        # 2 identical actions -> score 0.33
        history = [_cmd("ls"), _cmd_output(), _cmd("ls"), _cmd_output()]
        sd = StuckDetector(_state(history))  # type: ignore[arg-type]
        assert sd.compute_repetition_score() == 0.33

        # 3 identical actions -> score 0.67
        history.extend([_cmd("ls"), _cmd_output()])
        sd = StuckDetector(_state(history))  # type: ignore[arg-type]
        assert sd.compute_repetition_score() == 0.67

        # 4 identical actions -> score 1.0
        history.extend([_cmd("ls"), _cmd_output()])
        sd = StuckDetector(_state(history))  # type: ignore[arg-type]
        assert sd.compute_repetition_score() == 1.0

    def test_score_for_errors(self):
        # 3 errors -> score 1.0
        history = [
            _cmd("ls"), _error(),
            _cmd("cat"), _error(),
            _cmd("grep"), _error()
        ]
        sd = StuckDetector(_state(history))  # type: ignore[arg-type]
        assert sd.compute_repetition_score() == 1.0

    def test_score_for_mixed_failures(self):
        # 1 error + 1 exit_code 1 -> score 0.67
        history = [
            _cmd("ls"), _error(),
            _cmd("cat"), _cmd_output(exit_code=1)
        ]
        sd = StuckDetector(_state(history))  # type: ignore[arg-type]
        assert sd.compute_repetition_score() == 0.67

class TestSemanticLoopDetection:
    def test_semantic_loop_low_diversity_high_failure(self):
        # 6 actions with only 2 unique intents, all failing
        history: list[Any] = []
        for i in range(3):
            history.append(_cmd("ls folder1"))
            history.append(_cmd_output(exit_code=1))
            history.append(_cmd("cat file1"))
            history.append(_error())

        sd = StuckDetector(_state(history))  # type: ignore[arg-type]
        # unique intents: inspect_filesystem (ls), inspect_filesystem (cat) -> diversity = 1/6?
        # Wait, _categorize_cmd_action maps both to inspect_filesystem.
        # So unique intents = 1. Diversity = 1/6 = 0.16. Failure rate = 1.0.
        assert sd._is_stuck_semantic_loop(history) is True  # type: ignore[arg-type]

    def test_diverse_actions_not_semantic_loop(self):
        history = [
            _cmd("ls"), _cmd_output(),
            _cmd("pip install x"), _cmd_output(),
            _cmd("pytest"), _cmd_output(),
            _cmd("git clone"), _cmd_output(),
            _cmd("mkdir"), _cmd_output(),
            _cmd("python run.py"), _cmd_output()
        ]
        sd = StuckDetector(_state(history))  # type: ignore[arg-type]
        assert sd._is_stuck_semantic_loop(history) is False  # type: ignore[arg-type]

class TestAdvancedPatterns:
    def test_is_stuck_token_repetition(self):
        from backend.events.action.message import MessageAction
        msg = MessageAction(content="This is a very long repeating message that should trigger the detector.")
        msg._source = EventSource.AGENT
        history = [msg, msg, msg]
        sd = StuckDetector(_state(history))  # type: ignore[arg-type]
        assert sd._is_stuck_token_repetition(history) is True  # type: ignore[arg-type]

    def test_is_stuck_cost_acceleration(self):
        from backend.llm.metrics import Metrics, TokenUsage

        history: list[Any] = []
        for i in range(10):
            m = _cmd(f"cmd {i}")
            # Rapidly growing prompt tokens
            m.llm_metrics = Metrics()
            m.llm_metrics.token_usages = [  # type: ignore[union-attr]
                TokenUsage(prompt_tokens=i * 3000, completion_tokens=10)
            ]
            history.append(m)
            history.append(_cmd_output())

        sd = StuckDetector(_state(history))  # type: ignore[arg-type]
        assert sd._is_stuck_cost_acceleration(history) is True  # type: ignore[arg-type]
