"""Tests for backend.security.options module."""

import pytest

from backend.security.analyzer import SecurityAnalyzer
from backend.security.options import SecurityAnalyzers, get_security_analyzer


class TestSecurityAnalyzersRegistry:
    def test_default_registered(self):
        assert 'default' in SecurityAnalyzers

    def test_default_is_security_analyzer(self):
        assert SecurityAnalyzers['default'] is SecurityAnalyzer


class TestGetSecurityAnalyzer:
    def test_get_default(self):
        analyzer = get_security_analyzer()
        assert isinstance(analyzer, SecurityAnalyzer)

    def test_get_default_explicit(self):
        analyzer = get_security_analyzer('default')
        assert isinstance(analyzer, SecurityAnalyzer)

    def test_with_config(self):
        analyzer = get_security_analyzer(config={'key': 'value'})
        assert isinstance(analyzer, SecurityAnalyzer)

    def test_unknown_name_raises(self):
        with pytest.raises(KeyError):
            get_security_analyzer('nonexistent')
