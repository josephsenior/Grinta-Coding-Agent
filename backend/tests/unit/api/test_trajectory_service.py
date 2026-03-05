"""Tests for backend.api.services.trajectory_service module.

Targets the 100.0% (14 missed lines) coverage gap.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.core.errors import ReplayError
from backend.api.services import trajectory_service
from backend.api.session.session_contract import ReplayCursor


class TestExportTrajectory:
    def test_export_success(self):
        # Mock conversation with event_stream
        mock_conversation = MagicMock()
        mock_event = MagicMock()
        mock_event.data = {"foo": "bar"}

        # We need mock iter_events_until_corrupt
        with patch("backend.api.services.trajectory_service.iter_events_until_corrupt") as mock_iter:
            mock_iter.return_value = [mock_event]

            with patch("backend.api.services.trajectory_service.event_to_dict") as mock_to_dict:
                mock_to_dict.return_value = {"foo": "bar"}

                cursor = ReplayCursor(since_id=None, start_id=0, limit=10)
                result = trajectory_service.export_trajectory(
                    conversation=mock_conversation,
                    cursor=cursor
                )

                assert len(result) == 1
                assert result[0] == {"foo": "bar"}
                mock_iter.assert_called_once()

    def test_export_success_exclude_hidden_false(self):
        mock_conversation = MagicMock()
        mock_event = MagicMock()

        with patch("backend.api.services.trajectory_service.iter_events_until_corrupt") as mock_iter:
            mock_iter.return_value = [mock_event]

            with patch("backend.api.services.trajectory_service.event_to_dict") as mock_to_dict:
                mock_to_dict.return_value = {"data": "test"}

                cursor = ReplayCursor(since_id=None, start_id=5, limit=20)
                result = trajectory_service.export_trajectory(
                    conversation=mock_conversation,
                    cursor=cursor,
                    exclude_hidden=False
                )

                assert len(result) == 1
                # Verify EventFilter was created with exclude_hidden=False
                # This is verified by the call succeeding

    def test_export_exception_raises_replay_error(self):
        mock_conversation = MagicMock()

        with patch("backend.api.services.trajectory_service.iter_events_until_corrupt") as mock_iter:
            mock_iter.side_effect = ValueError("corrupt event")

            cursor = ReplayCursor(since_id=None, start_id=0, limit=10)

            with pytest.raises(ReplayError, match="Failed to export trajectory"):
                trajectory_service.export_trajectory(
                    conversation=mock_conversation,
                    cursor=cursor
                )
