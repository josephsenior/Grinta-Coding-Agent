"""Unit tests for backend.execution.acceptance_criteria."""

from __future__ import annotations

from typing import cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from backend.execution.acceptance_criteria import AcceptanceCriteriaMixin
from backend.ledger.action import AcceptanceCriteriaAction
from backend.ledger.observation import (
    AcceptanceCriteriaObservation,
    ErrorObservation,
)


class TestAcceptanceCriteriaMixin(TestCase):
    def setUp(self):
        self.mixin = AcceptanceCriteriaMixin()
        self.mixin.sid = 'test-sid-123'
        self.mixin.event_stream = MagicMock()
        self.mixin.event_stream.user_id = 'user-123'

    def test_handle_no_event_stream(self):
        self.mixin.event_stream = None
        action = AcceptanceCriteriaAction(command='update', criteria_list=[])

        result = self.mixin._handle_acceptance_criteria_action(action)

        self.assertIsInstance(result, ErrorObservation)

    def test_handle_update_command(self):
        criteria_list = [
            {
                'assertion': 'Const assignment raises TypeError 409',
                'source': 'stated',
            },
            {
                'assertion': 'Nested struct const qualifiers extracted',
                'source': 'inferred',
            },
        ]
        action = AcceptanceCriteriaAction(command='update', criteria_list=criteria_list)

        with patch(
            'backend.execution.acceptance_criteria.get_conversation_dir',
            return_value='/tmp/conv/',
        ):
            with patch(
                'backend.core.criteria.acceptance_criteria_store.AcceptanceCriteriaStore.save_to_file'
            ):
                result = self.mixin._handle_acceptance_criteria_action(action)

        self.assertIsInstance(result, AcceptanceCriteriaObservation)
        obs = cast(AcceptanceCriteriaObservation, result)
        self.assertEqual(obs.command, 'update')
        self.assertEqual(len(obs.criteria_list), 2)
        self.mixin.event_stream.file_store.write.assert_called_once()

    def test_handle_view_reads_criteria_md(self):
        action = AcceptanceCriteriaAction(command='view', criteria_list=[])
        stored = '# Acceptance Criteria\n\n1. (stated) Example assertion\n'
        self.mixin.event_stream.file_store.read.return_value = stored

        with patch(
            'backend.execution.acceptance_criteria.get_conversation_dir',
            return_value='/tmp/conv/',
        ):
            result = self.mixin._handle_acceptance_criteria_action(action)

        obs = cast(AcceptanceCriteriaObservation, result)
        self.assertIn('Example assertion', obs.content)
        self.mixin.event_stream.file_store.write.assert_not_called()

    def test_generate_criteria_markdown_with_evidence(self):
        content = AcceptanceCriteriaMixin._generate_criteria_markdown(
            [
                {
                    'assertion': 'Tests pass',
                    'source': 'stated',
                    'evidence': 'pytest backend/tests/unit/foo.py',
                }
            ]
        )
        self.assertIn('(stated) Tests pass', content)
        self.assertIn('pytest backend/tests/unit/foo.py', content)
