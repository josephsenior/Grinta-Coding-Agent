"""Tests for backend/ledger/observation/server.py."""

from __future__ import annotations

from typing import Any, cast

from backend.ledger.observation.server import ServerReadyObservation


class TestServerReadyObservation:
    def _make(self, **kwargs) -> ServerReadyObservation:
        defaults = {
            "content": "",
            "port": 8080,
            "url": "http://localhost:8080",
        }
        defaults.update(kwargs)
        return ServerReadyObservation(**cast(Any, defaults))

    # ── Construction ────────────────────────────────────────────────

    def test_stores_port(self) -> None:
        obs = self._make(port=3000, url="http://localhost:3000")
        assert obs.port == 3000

    def test_stores_url(self) -> None:
        obs = self._make(url="http://0.0.0.0:9000")
        assert obs.url == "http://0.0.0.0:9000"

    def test_default_protocol_is_http(self) -> None:
        obs = self._make()
        assert obs.protocol == "http"

    def test_custom_protocol(self) -> None:
        obs = self._make(protocol="https")
        assert obs.protocol == "https"

    def test_default_health_status_is_unknown(self) -> None:
        obs = self._make()
        assert obs.health_status == "unknown"

    def test_custom_health_status(self) -> None:
        obs = self._make(health_status="healthy")
        assert obs.health_status == "healthy"

    # ── observation class variable ───────────────────────────────────

    def test_observation_type_is_server_ready(self) -> None:
        obs = self._make()
        # ObservationType.SERVER_READY has value "server_ready"
        assert obs.observation == "server_ready"

    def test_observation_is_class_var(self) -> None:
        # ClassVar should be consistent across instances
        a = self._make(port=1)
        b = self._make(port=2)
        assert a.observation == b.observation

    # ── message property ────────────────────────────────────────────

    def test_message_contains_url(self) -> None:
        obs = self._make(url="http://localhost:5000")
        assert "http://localhost:5000" in obs.message

    def test_message_healthy_shows_check_emoji(self) -> None:
        obs = self._make(health_status="healthy")
        assert "✅" in obs.message

    def test_message_unknown_status_shows_arrows_emoji(self) -> None:
        obs = self._make(health_status="unknown")
        assert "🔄" in obs.message

    def test_message_unhealthy_shows_arrows_emoji(self) -> None:
        obs = self._make(health_status="unhealthy")
        assert "🔄" in obs.message

    def test_message_is_string(self) -> None:
        obs = self._make()
        assert isinstance(obs.message, str)

    def test_message_mentions_server_ready(self) -> None:
        obs = self._make()
        msg = obs.message.lower()
        assert "server" in msg or "ready" in msg or "detected" in msg
