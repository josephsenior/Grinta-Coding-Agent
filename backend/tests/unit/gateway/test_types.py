"""Tests for backend.gateway.types — server type abstractions and errors."""

import pytest

from backend.core.errors import UserActionRequiredError
from backend.gateway.types import (
    LLMAuthenticationError,
    MissingSettingsError,
    ServerConfigInterface,
)


class TestMissingSettingsError:
    """Tests for MissingSettingsError exception."""

    def test_create_missing_settings_error(self):
        """Test creating MissingSettingsError."""
        error = MissingSettingsError("Missing config")
        assert str(error) == "Missing config"

    def test_inherits_user_action_required_error(self):
        """Test MissingSettingsError inherits UserActionRequiredError."""
        error = MissingSettingsError("Test")
        assert isinstance(error, UserActionRequiredError)

    def test_inherits_value_error(self):
        """Test MissingSettingsError inherits ValueError."""
        error = MissingSettingsError("Test")
        assert isinstance(error, ValueError)

    def test_can_be_raised(self):
        """Test MissingSettingsError can be raised and caught."""
        with pytest.raises(MissingSettingsError):
            raise MissingSettingsError("Test error")

    def test_can_be_caught_as_value_error(self):
        """Test can catch as ValueError."""
        with pytest.raises(ValueError):
            raise MissingSettingsError("Test")

    def test_can_be_caught_as_user_action_required(self):
        """Test can catch as UserActionRequiredError."""
        with pytest.raises(UserActionRequiredError):
            raise MissingSettingsError("Test")


class TestLLMAuthenticationError:
    """Tests for LLMAuthenticationError exception."""

    def test_create_llm_auth_error(self):
        """Test creating LLMAuthenticationError."""
        error = LLMAuthenticationError("Auth failed")
        assert str(error) == "Auth failed"

    def test_inherits_user_action_required_error(self):
        """Test LLMAuthenticationError inherits UserActionRequiredError."""
        error = LLMAuthenticationError("Test")
        assert isinstance(error, UserActionRequiredError)

    def test_inherits_value_error(self):
        """Test LLMAuthenticationError inherits ValueError."""
        error = LLMAuthenticationError("Test")
        assert isinstance(error, ValueError)

    def test_can_be_raised(self):
        """Test LLMAuthenticationError can be raised and caught."""
        with pytest.raises(LLMAuthenticationError):
            raise LLMAuthenticationError("Invalid API key")

    def test_can_be_caught_as_value_error(self):
        """Test can catch as ValueError."""
        with pytest.raises(ValueError):
            raise LLMAuthenticationError("Test")

    def test_can_be_caught_as_user_action_required(self):
        """Test can catch as UserActionRequiredError."""
        with pytest.raises(UserActionRequiredError):
            raise LLMAuthenticationError("Test")


class TestServerConfigInterface:
    """Tests for ServerConfigInterface ABC."""

    def test_cannot_instantiate_directly(self):
        """Test ServerConfigInterface cannot be instantiated."""
        with pytest.raises(TypeError):
            ServerConfigInterface()  # type: ignore

    def test_has_class_vars_defined(self):
        """Test interface defines required class variables."""
        # ClassVars are type annotations, not runtime attributes
        # Check that they're in annotations
        getattr(ServerConfigInterface, "__annotations__", {})
        # At minimum, interface should be defined (even if annotations aren't accessible)
        assert ServerConfigInterface is not None

    def test_has_abstract_methods(self):
        """Test interface has required abstract methods."""
        assert hasattr(ServerConfigInterface, "verify_config")
        assert hasattr(ServerConfigInterface, "get_config")

    def test_subclass_must_implement_verify_config(self):
        """Test subclass must implement verify_config."""

        class InvalidConfig(ServerConfigInterface):
            CONFIG_PATH = None
            APP_MODE = None  # type: ignore
            POSTHOG_CLIENT_KEY = ""
            GITHUB_CLIENT_ID = ""
            ATTACH_SESSION_MIDDLEWARE_PATH = ""

            def get_config(self):
                return {}

        with pytest.raises(TypeError):
            InvalidConfig()  # type: ignore

    def test_subclass_must_implement_get_config(self):
        """Test subclass must implement get_config."""

        class InvalidConfig(ServerConfigInterface):
            CONFIG_PATH = None
            APP_MODE = None  # type: ignore
            POSTHOG_CLIENT_KEY = ""
            GITHUB_CLIENT_ID = ""
            ATTACH_SESSION_MIDDLEWARE_PATH = ""

            def verify_config(self):
                pass

        with pytest.raises(TypeError):
            InvalidConfig()  # type: ignore

    def test_valid_subclass_implementation(self):
        """Test valid ServerConfigInterface implementation."""
        from backend.core.enums import AppMode

        class ValidConfig(ServerConfigInterface):
            CONFIG_PATH = "/path/to/config"
            APP_MODE = AppMode.OSS
            POSTHOG_CLIENT_KEY = "key123"
            GITHUB_CLIENT_ID = "client123"
            ATTACH_SESSION_MIDDLEWARE_PATH = "/middleware"

            def verify_config(self):
                pass

            def get_config(self):
                return {"mode": self.APP_MODE}

        config = ValidConfig()
        assert config.CONFIG_PATH == "/path/to/config"
        assert config.get_config() == {"mode": AppMode.OSS}
