"""Tests for event observation model types."""

import unittest
from dataclasses import fields as dc_fields

from backend.core.enums import RecallType
from backend.core.schemas import AgentState, ObservationType
from backend.events.observation.agent import (
    AgentCondensationObservation,
    AgentStateChangedObservation,
    AgentThinkObservation,
    PlaybookKnowledge,
    RecallFailureObservation,
    RecallObservation,
)
from backend.events.observation.error import ErrorObservation
from backend.events.observation.observation import Observation


class TestObservationBase(unittest.TestCase):
    """Test the Observation base class."""

    def test_observation_content(self):
        obs = Observation(content="test content")
        self.assertEqual(obs.content, "test content")

    def test_exit_code_default_none(self):
        obs = Observation(content="")
        self.assertIsNone(obs.exit_code)

    def test_exit_code_set_and_get(self):
        obs = Observation(content="")
        obs.exit_code = 42
        self.assertEqual(obs.exit_code, 42)

    def test_exit_code_set_none(self):
        obs = Observation(content="")
        obs.exit_code = 1
        obs.exit_code = None
        self.assertIsNone(obs.exit_code)


class TestErrorObservation(unittest.TestCase):
    """Test ErrorObservation."""

    def test_basic_construction(self):
        obs = ErrorObservation(content="Something failed")
        self.assertEqual(obs.content, "Something failed")
        self.assertEqual(obs.error_id, "")

    def test_with_error_id(self):
        obs = ErrorObservation(content="Error", error_id="ERR_001")
        self.assertEqual(obs.error_id, "ERR_001")

    def test_message_property(self):
        obs = ErrorObservation(content="Error message")
        self.assertEqual(obs.message, "Error message")

    def test_str_representation(self):
        obs = ErrorObservation(content="Bad thing happened")
        result = str(obs)
        self.assertIn("ErrorObservation", result)
        self.assertIn("Bad thing happened", result)

    def test_observation_type(self):
        self.assertEqual(ErrorObservation.observation, ObservationType.ERROR)


class TestAgentStateChangedObservation(unittest.TestCase):
    """Test AgentStateChangedObservation."""

    def test_construction_with_agent_state(self):
        obs = AgentStateChangedObservation(
            content="", agent_state=AgentState.RUNNING
        )
        self.assertEqual(obs.agent_state, AgentState.RUNNING)

    def test_construction_with_string(self):
        obs = AgentStateChangedObservation(content="", agent_state="custom_state")
        self.assertEqual(obs.agent_state, "custom_state")

    def test_reason_default(self):
        obs = AgentStateChangedObservation(
            content="", agent_state=AgentState.STOPPED
        )
        self.assertEqual(obs.reason, "")

    def test_reason_set(self):
        obs = AgentStateChangedObservation(
            content="", agent_state=AgentState.ERROR, reason="timeout"
        )
        self.assertEqual(obs.reason, "timeout")

    def test_message_is_empty(self):
        obs = AgentStateChangedObservation(
            content="ignored", agent_state=AgentState.FINISHED
        )
        self.assertEqual(obs.message, "")

    def test_observation_type(self):
        self.assertEqual(
            AgentStateChangedObservation.observation,
            ObservationType.AGENT_STATE_CHANGED,
        )


class TestAgentCondensationObservation(unittest.TestCase):
    """Test AgentCondensationObservation."""

    def test_message(self):
        obs = AgentCondensationObservation(content="Condensed summary")
        self.assertEqual(obs.message, "Condensed summary")

    def test_observation_type(self):
        self.assertEqual(
            AgentCondensationObservation.observation, ObservationType.CONDENSE
        )


class TestAgentThinkObservation(unittest.TestCase):
    """Test AgentThinkObservation."""

    def test_message(self):
        obs = AgentThinkObservation(content="Thought logged")
        self.assertEqual(obs.message, "Thought logged")

    def test_observation_type(self):
        self.assertEqual(AgentThinkObservation.observation, ObservationType.THINK)


class TestPlaybookKnowledge(unittest.TestCase):
    """Test PlaybookKnowledge dataclass."""

    def test_construction(self):
        pk = PlaybookKnowledge(
            name="py_best", trigger="python", content="Use venv"
        )
        self.assertEqual(pk.name, "py_best")
        self.assertEqual(pk.trigger, "python")
        self.assertEqual(pk.content, "Use venv")


class TestRecallObservation(unittest.TestCase):
    """Test RecallObservation."""

    def test_workspace_context_message(self):
        obs = RecallObservation(
            content="", recall_type=RecallType.WORKSPACE_CONTEXT
        )
        self.assertEqual(obs.message, "Added workspace context")

    def test_knowledge_message(self):
        obs = RecallObservation(
            content="", recall_type=RecallType.KNOWLEDGE
        )
        self.assertEqual(obs.message, "Added playbook knowledge")

    def test_default_fields(self):
        obs = RecallObservation(
            content="", recall_type=RecallType.WORKSPACE_CONTEXT
        )
        self.assertEqual(obs.repo_name, "")
        self.assertEqual(obs.repo_directory, "")
        self.assertEqual(obs.runtime_hosts, {})
        self.assertEqual(obs.playbook_knowledge, [])

    def test_str_workspace_context(self):
        obs = RecallObservation(
            content="",
            recall_type=RecallType.WORKSPACE_CONTEXT,
            repo_name="test-repo",
            date="2024-01-01",
        )
        result = str(obs)
        self.assertIn("RecallObservation", result)
        self.assertIn("repo_name=test-repo", result)

    def test_str_with_playbook_knowledge(self):
        pk = PlaybookKnowledge(name="git_tips", trigger="git", content="Use branches")
        obs = RecallObservation(
            content="",
            recall_type=RecallType.KNOWLEDGE,
            playbook_knowledge=[pk],
        )
        result = str(obs)
        self.assertIn("git_tips", result)

    def test_observation_type(self):
        self.assertEqual(RecallObservation.observation, ObservationType.RECALL)


class TestRecallFailureObservation(unittest.TestCase):
    """Test RecallFailureObservation."""

    def test_message_from_error(self):
        obs = RecallFailureObservation(
            content="", error_message="Connection failed"
        )
        self.assertEqual(obs.message, "Connection failed")

    def test_message_falls_back_to_content(self):
        obs = RecallFailureObservation(content="Fallback content")
        self.assertEqual(obs.message, "Fallback content")

    def test_recall_type_none(self):
        obs = RecallFailureObservation(content="Error")
        self.assertIsNone(obs.recall_type)

    def test_observation_type(self):
        self.assertEqual(
            RecallFailureObservation.observation, ObservationType.RECALL_FAILURE
        )


if __name__ == "__main__":
    unittest.main()
