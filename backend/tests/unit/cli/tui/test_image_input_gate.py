"""Tests for TUI vision capability gating."""

from __future__ import annotations

from types import SimpleNamespace

from backend.cli.tui.image_input_gate import image_input_blocked_reason


def test_image_input_blocked_when_vision_disabled() -> None:
    config = SimpleNamespace(model='gpt-4o', disable_vision=True)
    reason = image_input_blocked_reason(config)
    assert reason is not None
    assert 'disabled' in reason.lower()


def test_image_input_blocked_when_model_lacks_vision() -> None:
    config = SimpleNamespace(model='not-a-vision-model', disable_vision=False)
    reason = image_input_blocked_reason(config)
    assert reason is not None
    assert 'does not support' in reason.lower()


def test_image_input_allowed_for_vision_model(monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.cli.tui.image_input_gate.model_supports_vision',
        lambda model: model == 'vision-model',
    )
    config = SimpleNamespace(model='vision-model', disable_vision=False)
    assert image_input_blocked_reason(config) is None


def test_image_input_blocked_when_config_missing() -> None:
    reason = image_input_blocked_reason(None)
    assert reason is not None
