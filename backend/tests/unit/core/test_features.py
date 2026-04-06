"""Unit tests for backend.core.features — feature flag management."""

from __future__ import annotations

import pytest

from backend.core.features import (
    FeatureFlags,
    FeatureUnavailableError,
    get_feature_flags,
)


class TestFeatureUnavailableError:
    def test_default_message(self):
        err = FeatureUnavailableError('turbo_mode')
        assert err.feature_name == 'turbo_mode'
        assert 'turbo_mode' in str(err)
        assert 'not available' in str(err)

    def test_custom_message(self):
        err = FeatureUnavailableError('x', message='nope')
        assert str(err) == 'nope'
        assert err.feature_name == 'x'

    def test_is_exception(self):
        with pytest.raises(FeatureUnavailableError):
            raise FeatureUnavailableError('f')


class TestFeatureFlags:
    def test_init_no_config(self):
        flags = FeatureFlags()
        assert flags._config is None

    def test_security_risk_always_false(self):
        flags = FeatureFlags()
        assert flags.risk_assessment_enabled is False

    def test_with_config(self):
        sentinel = object()
        flags = FeatureFlags(config=sentinel)  # type: ignore[arg-type]
        assert flags._config is sentinel


class TestGetFeatureFlags:
    def test_returns_instance(self):
        ff = get_feature_flags()
        assert isinstance(ff, FeatureFlags)

    def test_passes_config(self):
        sentinel = object()
        ff = get_feature_flags(config=sentinel)  # type: ignore[arg-type]
        assert ff._config is sentinel
