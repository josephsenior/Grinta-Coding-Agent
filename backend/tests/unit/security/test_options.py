"""Tests for backend.security.options — security analyzer registry."""

import pytest

from backend.security.analyzer import SecurityAnalyzer
from backend.security.options import SecurityAnalyzers, get_security_analyzer


class TestSecurityAnalyzersRegistry:
    """Tests for SecurityAnalyzers registry."""

    def test_registry_exists(self):
        """Test SecurityAnalyzers registry is a dict."""
        assert isinstance(SecurityAnalyzers, dict)

    def test_default_analyzer_registered(self):
        """Test 'default' analyzer is registered."""
        assert "default" in SecurityAnalyzers

    def test_default_analyzer_is_security_analyzer_class(self):
        """Test default analyzer is SecurityAnalyzer class."""
        assert SecurityAnalyzers["default"] is SecurityAnalyzer

    def test_registry_can_be_extended(self):
        """Test registry can be extended with custom analyzers."""

        class CustomAnalyzer(SecurityAnalyzer):
            pass

        # Add custom analyzer
        SecurityAnalyzers["custom"] = CustomAnalyzer
        assert SecurityAnalyzers["custom"] is CustomAnalyzer

        # Clean up
        del SecurityAnalyzers["custom"]


class TestGetSecurityAnalyzer:
    """Tests for get_security_analyzer function."""

    def test_get_default_analyzer(self):
        """Test getting default analyzer."""
        analyzer = get_security_analyzer()
        assert isinstance(analyzer, SecurityAnalyzer)

    def test_get_default_analyzer_explicitly(self):
        """Test getting default analyzer by name."""
        analyzer = get_security_analyzer(name="default")
        assert isinstance(analyzer, SecurityAnalyzer)

    def test_get_default_analyzer_with_config(self):
        """Test getting default analyzer with config."""
        config = {"some_option": "value"}
        analyzer = get_security_analyzer(config=config)
        assert isinstance(analyzer, SecurityAnalyzer)

    def test_unknown_analyzer_raises_keyerror(self):
        """Test requesting unknown analyzer raises KeyError."""
        with pytest.raises(KeyError):
            get_security_analyzer(name="nonexistent")

    def test_get_analyzer_returns_instance_not_class(self):
        """Test get_security_analyzer returns instance, not class."""
        analyzer = get_security_analyzer()
        assert not isinstance(analyzer, type)
        assert isinstance(analyzer, SecurityAnalyzer)

    def test_multiple_calls_return_different_instances(self):
        """Test multiple calls create different instances."""
        analyzer1 = get_security_analyzer()
        analyzer2 = get_security_analyzer()
        assert analyzer1 is not analyzer2

    def test_config_none_works(self):
        """Test config=None works (default behavior)."""
        analyzer = get_security_analyzer(config=None)
        assert isinstance(analyzer, SecurityAnalyzer)

    def test_empty_config_works(self):
        """Test empty config dict works."""
        analyzer = get_security_analyzer(config={})
        assert isinstance(analyzer, SecurityAnalyzer)

    def test_custom_analyzer_in_registry(self):
        """Test getting custom analyzer from registry."""

        class TestCustomAnalyzer(SecurityAnalyzer):
            def __init__(self, config=None):
                super().__init__(config=config)
                self.custom_attr = "test"

        # Add to registry
        SecurityAnalyzers["test_custom"] = TestCustomAnalyzer

        try:
            analyzer = get_security_analyzer(name="test_custom")
            assert isinstance(analyzer, TestCustomAnalyzer)
            assert analyzer.custom_attr == "test"
        finally:
            # Clean up
            del SecurityAnalyzers["test_custom"]

    def test_analyzer_class_inheritance(self):
        """Test returned analyzer inherits from SecurityAnalyzer."""
        analyzer = get_security_analyzer()
        assert isinstance(analyzer, SecurityAnalyzer)

    def test_config_passed_to_analyzer(self):
        """Test config is passed to analyzer constructor."""

        class ConfigCaptureAnalyzer(SecurityAnalyzer):
            def __init__(self, config=None):
                super().__init__(config=config)
                self.captured_config = config

        SecurityAnalyzers["config_capture"] = ConfigCaptureAnalyzer

        try:
            test_config = {"key": "value", "number": 42}
            analyzer = get_security_analyzer(name="config_capture", config=test_config)
            assert analyzer.captured_config == test_config
        finally:
            del SecurityAnalyzers["config_capture"]
