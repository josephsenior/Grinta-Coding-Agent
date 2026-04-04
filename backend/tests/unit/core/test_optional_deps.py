"""Tests for backend.core.optional_deps — optional dependency loading."""

from unittest.mock import MagicMock, patch

import pytest

from backend.core.optional_deps import OptionalDependencyError, require_optional


class TestOptionalDependencyError:
    """Tests for OptionalDependencyError exception."""

    def test_create_error(self):
        """Test creating OptionalDependencyError."""
        error = OptionalDependencyError('Missing module')
        assert str(error) == 'Missing module'

    def test_inherits_import_error(self):
        """Test OptionalDependencyError inherits ImportError."""
        error = OptionalDependencyError('Test')
        assert isinstance(error, ImportError)

    def test_can_be_raised(self):
        """Test error can be raised and caught."""
        with pytest.raises(OptionalDependencyError):
            raise OptionalDependencyError('Test error')

    def test_can_be_caught_as_import_error(self):
        """Test can catch as ImportError."""
        with pytest.raises(ImportError):
            raise OptionalDependencyError('Test')


class TestRequireOptional:
    """Tests for require_optional function."""

    @patch('backend.core.optional_deps.importlib.import_module')
    def test_import_succeeds(self, mock_import):
        """Test importing available module."""
        mock_module = MagicMock()
        mock_import.return_value = mock_module

        result = require_optional('some_module', extra='optional')

        mock_import.assert_called_once_with('some_module')
        assert result == mock_module

    @patch('backend.core.optional_deps.importlib.import_module')
    def test_import_fails_raises_crisp_error(self, mock_import):
        """Test importing missing module raises crisp error."""
        mock_import.side_effect = ModuleNotFoundError("No module named 'missing'")

        with pytest.raises(
            OptionalDependencyError,
            match="Optional dependency 'missing_module' is required",
        ):
            require_optional('missing_module', extra='extra_name')

    @patch('backend.core.optional_deps.importlib.import_module')
    def test_error_message_includes_extra(self, mock_import):
        """Test error message includes extra name."""
        mock_import.side_effect = ModuleNotFoundError()

        with pytest.raises(
            OptionalDependencyError, match="pip install 'app-ai\\[test_extra\\]'"
        ):
            require_optional('test_module', extra='test_extra')

    @patch('backend.core.optional_deps.importlib.import_module')
    def test_chained_exception(self, mock_import):
        """Test raised exception chains from original error."""
        original_error = ModuleNotFoundError('Original')
        mock_import.side_effect = original_error

        with pytest.raises(OptionalDependencyError) as exc_info:
            require_optional('module', extra='extra')

        assert exc_info.value.__cause__ == original_error

    @patch('backend.core.optional_deps.importlib.import_module')
    def test_import_different_modules(self, mock_import):
        """Test importing different modules."""
        mock_module1 = MagicMock()
        mock_module2 = MagicMock()
        mock_import.side_effect = [mock_module1, mock_module2]

        result1 = require_optional('module1', extra='extra1')
        result2 = require_optional('module2', extra='extra2')

        assert result1 == mock_module1
        assert result2 == mock_module2
        assert mock_import.call_count == 2
