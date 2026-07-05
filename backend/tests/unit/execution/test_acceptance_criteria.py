"""Unit tests for backend.execution.acceptance_criteria."""

from __future__ import annotations

from typing import cast
from unittest import TestCase
from unittest.mock import MagicMock, patch

from backend.execution.acceptance_criteria import AcceptanceCriteriaMixin
from backend.ledger.action import AcceptanceCriteriaAction
from backend.ledger.infra.tool import ToolCallMetadata
from backend.ledger.observation import (
    AcceptanceCriteriaObservation,
    ErrorObservation,
    Observation,
)


class TestAcceptanceCriteriaMixin(TestCase):
    def setUp(self):
        self.mixin = AcceptanceCriteriaMixin()
        self.mixin.sid = 'test-sid-123'
        self.mixin.event_stream = MagicMock()
        self.mixin.event_stream.user_id = 'user-123'
        self.mixin.event_stream.search_events.return_value = []

    def test_handle_no_event_stream(self):
        self.mixin.event_stream = None
        action = AcceptanceCriteriaAction(command='update', criteria_list=[])

        result = self.mixin._handle_acceptance_criteria_action(action)

        self.assertIsInstance(result, ErrorObservation)

    def test_handle_update_command(self):
        criteria_list = [
            {
                'id': 'ac1',
                'assertion': 'Const assignment raises TypeError 409',
                'source': 'stated',
            },
            {
                'id': 'ac2',
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

    def test_handle_view_renders_from_json_store(self):
        criteria_list = [
            {
                'id': 'ac1',
                'assertion': 'Example assertion',
                'source': 'stated',
            }
        ]
        action = AcceptanceCriteriaAction(command='view', criteria_list=criteria_list)

        with patch(
            'backend.execution.acceptance_criteria.get_conversation_dir',
            return_value='/tmp/conv/',
        ):
            with patch(
                'backend.core.criteria.acceptance_criteria_store.AcceptanceCriteriaStore.load_from_file',
                return_value=criteria_list,
            ):
                result = self.mixin._handle_acceptance_criteria_action(action)

        obs = cast(AcceptanceCriteriaObservation, result)
        self.assertIn('Example assertion', obs.content)
        self.mixin.event_stream.file_store.read.assert_not_called()
        self.mixin.event_stream.file_store.write.assert_called_once()

    def test_generate_criteria_markdown_with_evidence_and_id(self):
        content = AcceptanceCriteriaMixin._generate_criteria_markdown(
            [
                {
                    'id': 'ac1',
                    'assertion': 'Tests pass',
                    'source': 'stated',
                    'evidence': 'pytest backend/tests/unit/foo.py',
                }
            ]
        )
        self.assertIn('[ac1] (stated) Tests pass', content)
        self.assertIn('pytest backend/tests/unit/foo.py', content)

    def test_handle_refine_command(self):
        action = AcceptanceCriteriaAction(
            command='refine',
            criterion_id='ac1',
            new_assertion='Timeout is 5 ticks',
            reason='3 ticks too short on WSL',
            criteria_list=[
                {'id': 'ac1', 'assertion': 'Timeout is 3 ticks', 'source': 'inferred'}
            ],
        )
        with patch(
            'backend.execution.acceptance_criteria.get_conversation_dir',
            return_value='/tmp/conv/',
        ):
            with patch(
                'backend.core.criteria.acceptance_criteria_store.AcceptanceCriteriaStore.load_from_file',
                return_value=[
                    {
                        'id': 'ac1',
                        'assertion': 'Timeout is 3 ticks',
                        'source': 'inferred',
                    }
                ],
            ):
                with patch(
                    'backend.core.criteria.acceptance_criteria_store.AcceptanceCriteriaStore.save_to_file'
                ):
                    result = self.mixin._handle_acceptance_criteria_action(action)

        obs = cast(AcceptanceCriteriaObservation, result)
        self.assertEqual(obs.command, 'refine')
        self.assertEqual(obs.criteria_list[0]['assertion'], 'Timeout is 5 ticks')
        self.assertEqual(len(obs.criteria_list[0]['changes']), 1)

    def test_audit_resolves_evidence_ref(self):
        obs = Observation(content='line1\nline2\nline3')
        obs.tool_call_metadata = ToolCallMetadata(
            function_name='run',
            tool_call_id='call_audit_1',
            model_response={},
            total_calls_in_response=1,
        )
        self.mixin.event_stream.search_events.return_value = [obs]
        action = AcceptanceCriteriaAction(
            command='audit',
            criteria_list=[
                {'id': 'ac1', 'assertion': 'Tests pass', 'source': 'stated'}
            ],
            audit_entries=[
                {'criterion_id': 'ac1', 'evidence_ref': 'call_audit_1:lines[2]'}
            ],
        )
        with patch(
            'backend.execution.acceptance_criteria.get_conversation_dir',
            return_value='/tmp/conv/',
        ):
            with patch(
                'backend.core.criteria.acceptance_criteria_store.AcceptanceCriteriaStore.save_to_file'
            ):
                result = self.mixin._handle_acceptance_criteria_action(action)

        obs_result = cast(AcceptanceCriteriaObservation, result)
        self.assertEqual(obs_result.criteria_list[0]['evidence'], 'line2')
        self.assertEqual(
            obs_result.criteria_list[0]['evidence_ref'], 'call_audit_1:lines[2]'
        )

    def test_audit_unresolved_evidence_ref_records_placeholder(self):
        action = AcceptanceCriteriaAction(
            command='audit',
            criteria_list=[
                {'id': 'ac1', 'assertion': 'Tests pass', 'source': 'stated'}
            ],
            audit_entries=[{'criterion_id': 'ac1', 'evidence_ref': 'call_missing'}],
        )
        with patch(
            'backend.execution.acceptance_criteria.get_conversation_dir',
            return_value='/tmp/conv/',
        ):
            with patch(
                'backend.core.criteria.acceptance_criteria_store.AcceptanceCriteriaStore.save_to_file'
            ):
                result = self.mixin._handle_acceptance_criteria_action(action)

        obs_result = cast(AcceptanceCriteriaObservation, result)
        self.assertIn('unresolved evidence_ref', obs_result.criteria_list[0]['evidence'])
        self.assertIn('Audit notes', obs_result.content)
