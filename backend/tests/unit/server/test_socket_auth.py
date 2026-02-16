"""Tests for backend.server.socket_auth module."""

from unittest.mock import patch

import pytest


class TestParseLatestEventId:
    def test_valid_integer(self):
        from backend.server.socket_auth import parse_latest_event_id

        assert parse_latest_event_id({"latest_event_id": ["42"]}) == 42

    def test_undefined_returns_minus_one(self):
        from backend.server.socket_auth import parse_latest_event_id

        assert parse_latest_event_id({"latest_event_id": ["undefined"]}) == -1

    def test_missing_key_returns_minus_one(self):
        from backend.server.socket_auth import parse_latest_event_id

        assert parse_latest_event_id({}) == -1

    def test_non_numeric_returns_minus_one(self):
        from backend.server.socket_auth import parse_latest_event_id

        assert parse_latest_event_id({"latest_event_id": ["abc"]}) == -1

    def test_zero(self):
        from backend.server.socket_auth import parse_latest_event_id

        assert parse_latest_event_id({"latest_event_id": ["0"]}) == 0

    def test_negative(self):
        from backend.server.socket_auth import parse_latest_event_id

        assert parse_latest_event_id({"latest_event_id": ["-5"]}) == -5


class TestParseProvidersSet:
    def test_single_provider(self):
        from backend.server.socket_auth import parse_providers_set

        result = parse_providers_set({"providers_set": ["enterprise_sso"]})
        assert len(result) == 1

    def test_comma_separated_providers(self):
        from backend.server.socket_auth import parse_providers_set

        result = parse_providers_set({"providers_set": ["enterprise_sso,enterprise_sso"]})
        assert len(result) == 2

    def test_empty_providers(self):
        from backend.server.socket_auth import parse_providers_set

        result = parse_providers_set({})
        assert result == []

    def test_empty_string_filtered(self):
        from backend.server.socket_auth import parse_providers_set

        result = parse_providers_set({"providers_set": [""]})
        assert result == []


class TestValidateConnectionParams:
    def test_missing_conversation_id_raises(self):
        from socketio.exceptions import ConnectionRefusedError

        from backend.server.socket_auth import validate_connection_params

        with pytest.raises(ConnectionRefusedError):
            validate_connection_params(None, {})

    def test_empty_conversation_id_raises(self):
        from socketio.exceptions import ConnectionRefusedError

        from backend.server.socket_auth import validate_connection_params

        with pytest.raises(ConnectionRefusedError):
            validate_connection_params("", {})

    @patch("backend.server.socket_auth.invalid_session_api_key", return_value=False)
    def test_valid_params_passes(self, mock_invalid):
        from backend.server.socket_auth import validate_connection_params

        # Should not raise
        validate_connection_params("conv-123", {})

    @patch("backend.server.socket_auth.invalid_session_api_key", return_value=True)
    def test_invalid_api_key_raises(self, mock_invalid):
        from socketio.exceptions import ConnectionRefusedError

        from backend.server.socket_auth import validate_connection_params

        with pytest.raises(ConnectionRefusedError, match="invalid_session_api_key"):
            validate_connection_params("conv-123", {})


class TestInvalidSessionApiKey:
    @patch("backend.server.socket_auth.server_config")
    def test_no_expected_key_returns_false(self, mock_config):
        from backend.server.socket_auth import invalid_session_api_key

        mock_config.session_api_key = ""
        assert invalid_session_api_key({}) is False

    @patch("backend.server.socket_auth.server_config")
    def test_valid_auth_payload_key(self, mock_config):
        from backend.server.socket_auth import invalid_session_api_key

        mock_config.session_api_key = "secret"
        assert invalid_session_api_key({}, auth={"session_api_key": "secret"}) is False

    @patch("backend.server.socket_auth.server_config")
    def test_valid_auth_api_key(self, mock_config):
        from backend.server.socket_auth import invalid_session_api_key

        mock_config.session_api_key = "secret"
        assert invalid_session_api_key({}, auth={"apiKey": "secret"}) is False

    @patch("backend.server.socket_auth.server_config")
    def test_valid_auth_token(self, mock_config):
        from backend.server.socket_auth import invalid_session_api_key

        mock_config.session_api_key = "secret"
        assert invalid_session_api_key({}, auth={"token": "secret"}) is False

    @patch("backend.server.socket_auth.server_config")
    def test_wrong_key_returns_true(self, mock_config):
        from backend.server.socket_auth import invalid_session_api_key

        mock_config.session_api_key = "secret"
        assert invalid_session_api_key({}, auth={"session_api_key": "wrong"}) is True

    @patch("backend.server.socket_auth.server_config")
    def test_missing_auth_returns_true(self, mock_config):
        from backend.server.socket_auth import invalid_session_api_key

        mock_config.session_api_key = "secret"
        assert invalid_session_api_key({}) is True

    @patch("backend.server.socket_auth.server_config")
    def test_none_auth_returns_true(self, mock_config):
        from backend.server.socket_auth import invalid_session_api_key

        mock_config.session_api_key = "secret"
        assert invalid_session_api_key({}, auth=None) is True
