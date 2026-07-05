"""Tests for acceptance_criteria tool and handlers."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from backend.core.tools.tool_names import ACCEPTANCE_CRITERIA_TOOL_NAME
from backend.engine.tools._tool_handlers import _handle_acceptance_criteria_tool
from backend.engine.tools.acceptance_criteria import create_acceptance_criteria_tool
from backend.ledger.action import AcceptanceCriteriaAction


def _func(tool: Any) -> Any:
    return tool['function']


def _params(tool: Any) -> Any:
    return _func(tool)['parameters']


class TestCreateAcceptanceCriteriaTool:
    def setup_method(self):
        self.tool = create_acceptance_criteria_tool()

    def test_name(self):
        assert _func(self.tool)['name'] == ACCEPTANCE_CRITERIA_TOOL_NAME

    def test_command_enum(self):
        enum = _params(self.tool)['properties']['command']['enum']
        assert enum == ['view', 'update', 'append', 'refine', 'audit']

    def test_criteria_item_requires_assertion_and_source(self):
        items = _params(self.tool)['properties']['criteria_list']['items']
        assert 'assertion' in items['required']
        assert 'source' in items['required']

    def test_refine_params_present(self):
        props = _params(self.tool)['properties']
        assert 'criterion_id' in props
        assert 'new_assertion' in props
        assert 'reason' in props

    def test_audit_entries_present(self):
        props = _params(self.tool)['properties']
        assert 'audit_entries' in props


class TestHandleAcceptanceCriteriaTool:
    def test_update_returns_action(self):
        args = {
            'command': 'update',
            'criteria_list': [
                {'assertion': 'API returns 200', 'source': 'stated'},
            ],
        }
        with patch(
            'backend.engine.tools._tool_handlers.AcceptanceCriteriaStore'
        ) as store_cls:
            store_cls.return_value.load_from_file.return_value = []
            action = _handle_acceptance_criteria_tool(args)
        assert isinstance(action, AcceptanceCriteriaAction)
        assert action.command == 'update'
        assert len(action.criteria_list) == 1

    def test_audit_legacy_requires_evidence(self):
        args = {
            'command': 'audit',
            'criteria_list': [
                {'assertion': 'API returns 200', 'source': 'stated'},
            ],
        }
        with pytest.raises(Exception, match='evidence'):
            _handle_acceptance_criteria_tool(args)

    def test_audit_entries_accepts_free_text_evidence(self):
        stored = [
            {
                'id': 'ac1',
                'assertion': 'Tests pass',
                'source': 'stated',
                'evidence': None,
            }
        ]
        args = {
            'command': 'audit',
            'audit_entries': [
                {
                    'criterion_id': 'ac1',
                    'evidence': 'pytest: 42 passed',
                },
            ],
        }
        with patch(
            'backend.engine.tools._tool_handlers.AcceptanceCriteriaStore'
        ) as store_cls:
            store_cls.return_value.load_from_file.return_value = stored
            action = _handle_acceptance_criteria_tool(args)
        assert action.command == 'audit'
        assert action.audit_entries[0]['evidence'] == 'pytest: 42 passed'

    def test_refine_requires_reason(self):
        stored = [{'id': 'ac1', 'assertion': 'A', 'source': 'stated'}]
        with patch(
            'backend.engine.tools._tool_handlers.AcceptanceCriteriaStore'
        ) as store_cls:
            store_cls.return_value.load_from_file.return_value = stored
            with pytest.raises(Exception, match='reason'):
                _handle_acceptance_criteria_tool(
                    {
                        'command': 'refine',
                        'criterion_id': 'ac1',
                        'new_assertion': 'B',
                    }
                )

    def test_refine_returns_action(self):
        stored = [{'id': 'ac1', 'assertion': 'A', 'source': 'stated'}]
        with patch(
            'backend.engine.tools._tool_handlers.AcceptanceCriteriaStore'
        ) as store_cls:
            store_cls.return_value.load_from_file.return_value = stored
            action = _handle_acceptance_criteria_tool(
                {
                    'command': 'refine',
                    'criterion_id': 'ac1',
                    'new_assertion': 'B',
                    'reason': 'discovered during implementation',
                }
            )
        assert action.command == 'refine'
        assert action.criterion_id == 'ac1'

    def test_view_loads_from_store(self):
        stored = [
            {
                'id': 'ac1',
                'assertion': 'Saved item',
                'source': 'stated',
                'evidence': None,
            }
        ]
        with patch(
            'backend.engine.tools._tool_handlers.AcceptanceCriteriaStore'
        ) as store_cls:
            store_cls.return_value.load_from_file.return_value = stored
            action = _handle_acceptance_criteria_tool({'command': 'view'})
        assert action.criteria_list == stored
