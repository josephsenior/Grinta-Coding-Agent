from __future__ import annotations

from backend.engine.safety import OrchestratorSafetyManager
from backend.ledger.action import MessageAction, ProposalAction


def test_safety_blocks_explicit_file_claim_in_plain_message():
    safety = OrchestratorSafetyManager()

    proceed, actions = safety.apply(
        "I've created grinta_feedback.md with the full write-up.",
        [MessageAction(content="I've created grinta_feedback.md with the full write-up.")],
    )

    assert proceed is True
    assert len(actions) == 1


def test_safety_blocks_explicit_command_claim_in_plain_message():
    safety = OrchestratorSafetyManager()

    proceed, actions = safety.apply(
        "I've run the tests and they all passed.",
        [MessageAction(content="I've run the tests and they all passed.")],
    )

    assert proceed is True
    assert len(actions) == 1


def test_safety_allows_conversational_plain_message_without_side_effect_claim():
    safety = OrchestratorSafetyManager()

    proceed, actions = safety.apply(
        "I've prepared a rating of the system and the tools based on the transcript.",
        [
            MessageAction(
                content="I've prepared a rating of the system and the tools based on the transcript."
            )
        ],
    )

    assert proceed is True
    assert len(actions) == 1


def test_safety_allows_structured_non_runnable_actions():
    safety = OrchestratorSafetyManager()

    proceed, actions = safety.apply(
        "I've prepared two approaches for your feedback.",
        [
            ProposalAction(
                options=[{'approach': 'Summarize tradeoffs directly', 'pros': [], 'cons': []}],
                rationale='Two approaches are available.',
            )
        ],
    )

    assert proceed is True
    assert len(actions) == 1
