"""Tests for backend.gateway.socketio_connection_params module."""

import pytest


class TestParseLatestEventId:
    def test_valid_integer(self):
        from backend.gateway.socketio_connection_params import parse_latest_event_id

        assert parse_latest_event_id({"latest_event_id": ["42"]}) == 42

    def test_undefined_returns_minus_one(self):
        from backend.gateway.socketio_connection_params import parse_latest_event_id

        assert parse_latest_event_id({"latest_event_id": ["undefined"]}) == -1

    def test_missing_key_returns_minus_one(self):
        from backend.gateway.socketio_connection_params import parse_latest_event_id

        assert parse_latest_event_id({}) == -1

    def test_non_numeric_returns_minus_one(self):
        from backend.gateway.socketio_connection_params import parse_latest_event_id

        assert parse_latest_event_id({"latest_event_id": ["abc"]}) == -1


class TestParseProvidersSet:
    def test_single_provider(self):
        from backend.gateway.socketio_connection_params import parse_providers_set

        result = parse_providers_set({"providers_set": ["enterprise_sso"]})
        assert len(result) == 1

    def test_empty_providers(self):
        from backend.gateway.socketio_connection_params import parse_providers_set

        assert parse_providers_set({}) == []


class TestValidateConnectionParams:
    def test_missing_conversation_id_raises(self):
        from socketio.exceptions import ConnectionRefusedError

        from backend.gateway.socketio_connection_params import validate_connection_params

        with pytest.raises(ConnectionRefusedError):
            validate_connection_params(None)

    def test_empty_conversation_id_raises(self):
        from socketio.exceptions import ConnectionRefusedError

        from backend.gateway.socketio_connection_params import validate_connection_params

        with pytest.raises(ConnectionRefusedError):
            validate_connection_params("")

    def test_valid_params_passes(self):
        from backend.gateway.socketio_connection_params import validate_connection_params

        validate_connection_params("conv-123")

