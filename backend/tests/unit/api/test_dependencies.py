"""Tests for backend.api.services.dependencies module.

Targets the 66.7% (4 missed lines) coverage gap.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.api.services import dependencies


class TestConversationManagerDependency:
    @patch("backend.api.services.dependencies.get_conversation_manager")
    def test_get_instance_success(self, mock_get):
        mock_get.return_value = "manager"
        assert dependencies.get_conversation_manager_instance() == "manager"

    @patch("backend.api.services.dependencies.get_conversation_manager")
    def test_get_instance_failure(self, mock_get):
        mock_get.side_effect = Exception("init error")
        assert dependencies.get_conversation_manager_instance() is None

    @patch("backend.api.services.dependencies.get_conversation_manager_instance")
    def test_require_success(self, mock_get_inst):
        mock_get_inst.return_value = "manager"
        assert dependencies.require_conversation_manager() == "manager"

    @patch("backend.api.services.dependencies.get_conversation_manager_instance")
    def test_require_failure_raises_503(self, mock_get_inst):
        mock_get_inst.return_value = None
        with pytest.raises(HTTPException) as exc:
            dependencies.require_conversation_manager()
        assert exc.value.status_code == 503


class TestEventServiceAdapterDependency:
    @patch("backend.api.services.dependencies.get_event_service_adapter")
    def test_get_instance_success(self, mock_get):
        mock_get.return_value = "adapter"
        assert dependencies.get_event_service_adapter_instance() == "adapter"

    @patch("backend.api.services.dependencies.get_event_service_adapter")
    def test_get_instance_failure(self, mock_get):
        mock_get.side_effect = Exception("init error")
        assert dependencies.get_event_service_adapter_instance() is None

    @patch("backend.api.services.dependencies.get_event_service_adapter_instance")
    def test_require_success(self, mock_get_inst):
        mock_get_inst.return_value = "adapter"
        assert dependencies.require_event_service_adapter() == "adapter"

    @patch("backend.api.services.dependencies.get_event_service_adapter_instance")
    def test_require_failure_raises_503(self, mock_get_inst):
        mock_get_inst.return_value = None
        with pytest.raises(HTTPException) as exc:
            dependencies.require_event_service_adapter()
        assert exc.value.status_code == 503
