"""Tests for backend.code_quality.impl — code linting with multiple backends."""


from backend.code_quality.impl import DefaultLinter, LintError, LintResult


class TestLintError:
    """Tests for LintError dataclass."""

    def test_create_minimal_lint_error(self):
        """Test creating LintError with minimal fields."""
        error = LintError(line=10, column=5, message="Undefined variable")
        assert error.line == 10
        assert error.column == 5
        assert error.message == "Undefined variable"
        assert error.code is None
        assert error.severity == "error"
        assert error.file_path is None

    def test_create_full_lint_error(self):
        """Test creating LintError with all fields."""
        error = LintError(
            line=42,
            column=19,
            message="Line too long",
            code="E501",
            severity="warning",
            file_path="/path/to/file.py",
        )
        assert error.line == 42
        assert error.column == 19
        assert error.message == "Line too long"
        assert error.code == "E501"
        assert error.severity == "warning"
        assert error.file_path == "/path/to/file.py"

    def test_visualize_with_column_and_code(self):
        """Test visualizing lint error with column and code."""
        error = LintError(
            line=10, column=5, message="Undefined variable 'x'", code="F821"
        )
        result = error.visualize()
        assert "line 10" in result
        assert "column 5" in result
        assert "[F821]" in result
        assert "Undefined variable 'x'" in result

    def test_visualize_without_column(self):
        """Test visualizing lint error without column."""
        error = LintError(line=10, column=None, message="Import not used")
        result = error.visualize()
        assert "line 10" in result
        assert "column" not in result
        assert "Import not used" in result

    def test_visualize_without_code(self):
        """Test visualizing lint error without code."""
        error = LintError(line=10, column=5, message="Syntax error")
        result = error.visualize()
        assert "line 10, column 5" in result
        assert "[" not in result  # No code brackets
        assert "Syntax error" in result

    def test_severity_values(self):
        """Test different severity values."""
        error_obj = LintError(line=1, column=1, message="Error", severity="error")
        warning_obj = LintError(line=2, column=2, message="Warning", severity="warning")
        assert error_obj.severity == "error"
        assert warning_obj.severity == "warning"

    def test_line_zero(self):
        """Test lint error at line 0."""
        error = LintError(line=0, column=0, message="File-level error")
        assert error.line == 0


class TestLintResult:
    """Tests for LintResult dataclass."""

    def test_create_empty_result(self):
        """Test creating empty LintResult."""
        result = LintResult(errors=[], warnings=[])
        assert result.errors == []
        assert result.warnings == []

    def test_create_with_errors_only(self):
        """Test creating LintResult with errors only."""
        error1 = LintError(line=1, column=1, message="Error 1", severity="error")
        error2 = LintError(line=2, column=2, message="Error 2", severity="error")
        result = LintResult(errors=[error1, error2], warnings=[])
        assert len(result.errors) == 2
        assert len(result.warnings) == 0

    def test_create_with_warnings_only(self):
        """Test creating LintResult with warnings only."""
        warning1 = LintError(line=1, column=1, message="Warning 1", severity="warning")
        warning2 = LintError(line=2, column=2, message="Warning 2", severity="warning")
        result = LintResult(errors=[], warnings=[warning1, warning2])
        assert len(result.errors) == 0
        assert len(result.warnings) == 2

    def test_create_with_mixed_issues(self):
        """Test creating LintResult with both errors and warnings."""
        error = LintError(line=1, column=1, message="Error", severity="error")
        warning = LintError(line=2, column=2, message="Warning", severity="warning")
        result = LintResult(errors=[error], warnings=[warning])
        assert len(result.errors) == 1
        assert len(result.warnings) == 1

    def test_post_init_separates_errors_and_warnings(self):
        """Test __post_init__ properly separates errors and warnings."""
        error = LintError(line=1, column=1, message="Error", severity="error")
        warning = LintError(line=2, column=2, message="Warning", severity="warning")
        # Pass both in errors list
        result = LintResult(errors=[error, warning], warnings=[])
        assert len(result.errors) == 1  # Only error
        assert len(result.warnings) == 1  # Warning separated
        assert result.errors[0].severity == "error"
        assert result.warnings[0].severity == "warning"

    def test_post_init_with_mixed_in_warnings_list(self):
        """Test __post_init__ handles mixed severity in warnings list."""
        error = LintError(line=1, column=1, message="Error", severity="error")
        warning = LintError(line=2, column=2, message="Warning", severity="warning")
        # Pass both in warnings list
        result = LintResult(errors=[], warnings=[error, warning])
        assert len(result.errors) == 1  # Error separated
        assert len(result.warnings) == 1  # Only warning
        assert result.errors[0].message == "Error"
        assert result.warnings[0].message == "Warning"

    def test_lint_file_diff_returns_empty_list(self):
        """Test lint_file_diff returns empty list by default."""
        result = LintResult(errors=[], warnings=[])
        diff_errors = result.lint_file_diff("original.py", "updated.py")
        assert diff_errors == []

    def test_lint_file_returns_empty_list(self):
        """Test lint_file returns empty list by default."""
        result = LintResult(errors=[], warnings=[])
        file_errors = result.lint_file("test.py")
        assert file_errors == []


class TestDefaultLinter:
    """Tests for DefaultLinter class."""

    def test_create_with_defaults(self):
        """Test creating DefaultLinter with default settings."""
        linter = DefaultLinter()
        assert linter.backend == "auto"
        assert linter.config_path is None
        assert linter.enable_cache is True
        assert linter.cache_ttl == 300
        assert linter._max_cache_size == 1000

    def test_create_with_specific_backend(self):
        """Test creating DefaultLinter with specific backend."""
        linter = DefaultLinter(backend="ruff")
        assert linter.backend == "ruff"

    def test_create_with_custom_config(self):
        """Test creating DefaultLinter with custom config path."""
        linter = DefaultLinter(config_path="/path/to/config.toml")
        assert linter.config_path == "/path/to/config.toml"

    def test_create_with_cache_disabled(self):
        """Test creating DefaultLinter with cache disabled."""
        linter = DefaultLinter(enable_cache=False)
        assert linter.enable_cache is False

    def test_create_with_custom_cache_settings(self):
        """Test creating DefaultLinter with custom cache settings."""
        linter = DefaultLinter(cache_ttl=600, max_cache_size=2000)
        assert linter.cache_ttl == 600
        assert linter._max_cache_size == 2000

    def test_cache_initialized_empty(self):
        """Test cache is initialized empty."""
        linter = DefaultLinter()
        assert len(linter._cache) == 0
        assert linter._cache_hits == 0
        assert linter._cache_misses == 0

    def test_backend_detection_auto_mode(self):
        """Test backend detection in auto mode."""
        linter = DefaultLinter(backend="auto")
        # Should detect a backend or be None
        assert linter._detected_backend in [None, "ruff", "pylint", "tree-sitter"]

    def test_multiple_backends(self):
        """Test creating linters with different backends."""
        backends = ["auto", "ruff", "pylint", "tree-sitter"]
        for backend in backends:
            linter = DefaultLinter(backend=backend)
            assert linter.backend == backend

    def test_cache_is_ordered_dict(self):
        """Test cache uses OrderedDict for LRU behavior."""
        linter = DefaultLinter()
        from collections import OrderedDict
        assert isinstance(linter._cache, OrderedDict)

    def test_cache_metrics_initialization(self):
        """Test cache metrics are initialized to zero."""
        linter = DefaultLinter()
        assert linter._cache_hits == 0
        assert linter._cache_misses == 0

    def test_linter_with_all_parameters(self):
        """Test creating linter with all constructor parameters."""
        linter = DefaultLinter(
            backend="pylint",
            config_path="/custom/config.toml",
            enable_cache=False,
            cache_ttl=1800,
            max_cache_size=500,
        )
        assert linter.backend == "pylint"
        assert linter.config_path == "/custom/config.toml"
        assert linter.enable_cache is False
        assert linter.cache_ttl == 1800
        assert linter._max_cache_size == 500


class TestLintingWorkflow:
    """Tests for linting workflow integration."""

    def test_lint_result_can_hold_multiple_errors(self):
        """Test LintResult can hold multiple errors."""
        errors = [
            LintError(line=i, column=i, message=f"Error {i}", severity="error")
            for i in range(1, 11)
        ]
        result = LintResult(errors=errors, warnings=[])
        assert len(result.errors) == 10

    def test_lint_result_can_hold_multiple_warnings(self):
        """Test LintResult can hold multiple warnings."""
        warnings = [
            LintError(line=i, column=i, message=f"Warning {i}", severity="warning")
            for i in range(1, 11)
        ]
        result = LintResult(errors=[], warnings=warnings)
        assert len(result.warnings) == 10

    def test_lint_error_formatting_consistency(self):
        """Test lint error formatting is consistent."""
        error1 = LintError(line=10, column=5, message="Test error", code="E001")
        error2 = LintError(line=10, column=5, message="Test error", code="E001")
        assert error1.visualize() == error2.visualize()

    def test_severity_based_separation(self):
        """Test LintResult separates issues by severity."""
        issues = [
            LintError(line=1, column=1, message="E1", severity="error"),
            LintError(line=2, column=2, message="W1", severity="warning"),
            LintError(line=3, column=3, message="E2", severity="error"),
            LintError(line=4, column=4, message="W2", severity="warning"),
        ]
        result = LintResult(errors=issues, warnings=[])
        assert len(result.errors) == 2
        assert len(result.warnings) == 2
        assert all(e.severity == "error" for e in result.errors)
        assert all(w.severity == "warning" for w in result.warnings)
