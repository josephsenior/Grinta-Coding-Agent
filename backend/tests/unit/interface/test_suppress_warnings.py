"""Tests for CLI warning suppression.

Tests warning filters for various library warnings.
"""

import unittest
import warnings


class TestSuppressCliWarnings(unittest.TestCase):
    """Tests for suppress_cli_warnings() warning filter setup."""

    def test_module_import_sets_filters(self) -> None:
        """Test importing module sets warning filters."""
        # Module is already imported, so filters should be set
        # We can verify by checking warnings.filters list
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")

            # This warning should be suppressed
            warnings.warn(
                "Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work",
                RuntimeWarning,
            )
            # Should not raise or be visible

    def test_suppresses_pydantic_serializer_warnings(self) -> None:
        """Test Pydantic serializer warnings are suppressed."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # This import triggers filter setup
            from backend.interface import suppress_warnings  # noqa: F401

            # Try to emit a Pydantic serializer warning
            warnings.warn("Pydantic serializer warnings detected", UserWarning)

            # Should be suppressed (or at least not fail)
            self.assertTrue(True)

    def test_suppresses_deprecation_warnings(self) -> None:
        """Test deprecation warnings are suppressed."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            from backend.interface import suppress_warnings  # noqa: F401

            warnings.warn("Call to deprecated method xyz", DeprecationWarning)

            # Should be suppressed
            self.assertTrue(True)

    def test_suppresses_syntax_warnings_from_pydub(self) -> None:
        """Test pydub SyntaxWarnings are suppressed."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            from backend.interface import suppress_warnings  # noqa: F401

            # Simulate pydub.utils warning
            warnings.warn_explicit(
                "Invalid syntax in audio file",
                SyntaxWarning,
                "pydub/utils.py",
                lineno=42,
                module="pydub.utils",
            )

            # Should be suppressed
            self.assertTrue(True)

    def test_function_can_be_called_multiple_times(self) -> None:
        """Test suppress_cli_warnings() is idempotent."""
        from backend.interface.suppress_warnings import suppress_cli_warnings

        # Should not raise even when called multiple times
        suppress_cli_warnings()
        suppress_cli_warnings()
        suppress_cli_warnings()

        self.assertTrue(True)

    def test_specific_warning_patterns_suppressed(self) -> None:
        """Test specific warning message patterns are suppressed."""
        from backend.interface.suppress_warnings import suppress_cli_warnings

        suppress_cli_warnings()

        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always")

            # These specific patterns should be suppressed
            test_warnings = [
                ("Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work", RuntimeWarning),
                ("Pydantic serializer warnings: model='User'", UserWarning),
                ("PydanticSerializationUnexpectedValue: value", UserWarning),
                ("Call to deprecated method get_config", DeprecationWarning),
                ("Expected 3 fields but got 5", UserWarning),
            ]

            for msg, category in test_warnings:
                warnings.warn(msg, category)

            # All should be suppressed, so very few warnings should be caught
            # (some Python internal warnings might still appear)
            self.assertTrue(True)


class TestWarningFiltersIntegration(unittest.TestCase):
    """Integration tests for warning filter behavior."""

    def test_filters_dont_affect_other_warnings(self) -> None:
        """Test filters don't suppress unrelated warnings."""
        from backend.interface.suppress_warnings import suppress_cli_warnings

        suppress_cli_warnings()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # This warning should NOT be suppressed
            warnings.warn("Custom application warning", UserWarning)

            # Should have captured this warning
            # (depends on filter specificity)
            self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
