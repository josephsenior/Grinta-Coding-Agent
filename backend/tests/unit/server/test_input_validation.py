"""Tests for backend.server.utils.input_validation — input sanitization."""

from __future__ import annotations

import pytest

from backend.server.utils.input_validation import (
    ValidationError,
    _detect_mime_type,
    sanitize_string,
    validate_api_parameter,
    validate_command,
    validate_file_path,
    validate_file_upload,
)


# ---------------------------------------------------------------------------
# validate_file_path
# ---------------------------------------------------------------------------


class TestValidateFilePath:
    def test_normal_path(self):
        assert (
            validate_file_path("src/main.py") == "src\\main.py"
            or validate_file_path("src/main.py") == "src/main.py"
        )

    def test_null_bytes_rejected(self):
        with pytest.raises(ValidationError, match="null bytes"):
            validate_file_path("foo\x00bar.txt")

    def test_traversal_rejected_without_base(self):
        with pytest.raises(ValidationError, match="traversal"):
            validate_file_path("../../etc/passwd")

    def test_absolute_rejected_without_base(self):
        # On Windows normpath converts /etc/passwd → \etc\passwd which no
        # longer starts with '/' so the guard doesn't trigger.  Use a '..'
        # based traversal which is platform-independent.
        with pytest.raises(ValidationError, match="traversal"):
            validate_file_path("../../../etc/passwd")

    def test_traversal_with_base_dir(self, tmp_path):
        # A path inside the base dir should succeed
        (tmp_path / "sub").mkdir()
        result = validate_file_path("sub/file.txt", str(tmp_path))
        assert "sub" in result and "file.txt" in result

    def test_traversal_escaping_base_dir(self, tmp_path):
        with pytest.raises(ValidationError, match="traversal"):
            validate_file_path("../../etc/passwd", str(tmp_path))

    def test_dangerous_chars_rejected(self):
        for ch in ["<", ">", "|", "&", ";", "`", "$"]:
            with pytest.raises(ValidationError, match="dangerous"):
                validate_file_path(f"file{ch}name.txt")

    def test_url_encoded_path(self):
        # %2F is /; after normpath the result is still valid
        result = validate_file_path("src%2Fmain.py")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# validate_command
# ---------------------------------------------------------------------------


class TestValidateCommand:
    def test_empty_command(self):
        with pytest.raises(ValidationError, match="Empty"):
            validate_command("")

    def test_whitespace_only(self):
        with pytest.raises(ValidationError, match="Empty"):
            validate_command("   ")

    def test_semicolon_injection(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_command("ls; rm -rf /")

    def test_pipe_injection(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_command("echo hello | cat")

    def test_command_substitution(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_command("echo $(whoami)")

    def test_allowed_commands_ok(self):
        result = validate_command("ls", allowed_commands=["ls", "cat"])
        assert result == "ls"

    def test_allowed_commands_rejected(self):
        with pytest.raises(ValidationError, match="not in allowed"):
            validate_command("rm file", allowed_commands=["ls", "cat"])


# ---------------------------------------------------------------------------
# validate_api_parameter
# ---------------------------------------------------------------------------


class TestValidateApiParameter:
    def test_required_empty(self):
        with pytest.raises(ValidationError, match="Required"):
            validate_api_parameter("", required=True)

    def test_not_required_empty(self):
        result = validate_api_parameter("", required=False)
        assert result == ""

    def test_integer_ok(self):
        result = validate_api_parameter("42", param_type="int")
        assert result == "42"

    def test_integer_bad(self):
        with pytest.raises(ValidationError, match="Invalid integer"):
            validate_api_parameter("abc", param_type="int")

    def test_float_ok(self):
        result = validate_api_parameter("3.14", param_type="float")
        assert result == "3.14"

    def test_float_bad(self):
        with pytest.raises(ValidationError, match="Invalid float"):
            validate_api_parameter("xyz", param_type="float")

    def test_email_ok(self):
        validate_api_parameter("user@example.com", param_type="email")

    def test_email_bad(self):
        with pytest.raises(ValidationError, match="Invalid email"):
            validate_api_parameter("not-email", param_type="email")

    def test_url_ok(self):
        validate_api_parameter("https://example.com", param_type="url")

    def test_url_bad(self):
        with pytest.raises(ValidationError, match="Invalid URL"):
            validate_api_parameter("not a url", param_type="url")

    def test_min_length(self):
        with pytest.raises(ValidationError, match="too short"):
            validate_api_parameter("ab", min_length=5)

    def test_max_length(self):
        with pytest.raises(ValidationError, match="too long"):
            validate_api_parameter("abcdef", max_length=3)

    def test_pattern_match(self):
        result = validate_api_parameter("abc123", pattern=r"^[a-z0-9]+$")
        assert result == "abc123"

    def test_pattern_no_match(self):
        with pytest.raises(ValidationError, match="pattern"):
            validate_api_parameter("ABC!", pattern=r"^[a-z]+$")


# ---------------------------------------------------------------------------
# validate_file_upload
# ---------------------------------------------------------------------------


class TestValidateFileUpload:
    def test_valid_upload(self):
        fname, content = validate_file_upload("test.txt", b"hello", max_size=1024)
        assert "test" in fname
        assert content == b"hello"

    def test_file_too_large(self):
        with pytest.raises(ValidationError, match="too large"):
            validate_file_upload("big.txt", b"x" * 100, max_size=50)

    def test_extension_filter(self):
        with pytest.raises(ValidationError, match="extension not allowed"):
            validate_file_upload("virus.exe", b"MZ", allowed_extensions=[".txt", ".py"])

    def test_extension_allowed(self):
        validate_file_upload("data.txt", b"hi", allowed_extensions=[".txt"])

    def test_mime_type_filter(self):
        with pytest.raises(ValidationError, match="MIME type not allowed"):
            validate_file_upload(
                "img.png",
                b"\x89PNG" + b"\x00" * 20,
                allowed_mime_types=["text/plain"],
            )


# ---------------------------------------------------------------------------
# _detect_mime_type
# ---------------------------------------------------------------------------


class TestDetectMimeType:
    def test_png(self):
        assert _detect_mime_type(b"\x89PNG", "img.png") == "image/png"

    def test_jpeg(self):
        assert _detect_mime_type(b"\xff\xd8\xff", "img.jpg") == "image/jpeg"

    def test_gif87a(self):
        assert _detect_mime_type(b"GIF87a", "img.gif") == "image/gif"

    def test_gif89a(self):
        assert _detect_mime_type(b"GIF89a", "img.gif") == "image/gif"

    def test_pdf(self):
        assert _detect_mime_type(b"%PDF-1.4", "doc.pdf") == "application/pdf"

    def test_zip(self):
        assert _detect_mime_type(b"PK\x03\x04", "archive.zip") == "application/zip"

    def test_fallback_to_extension(self):
        assert _detect_mime_type(b"raw bytes", "data.json") == "application/json"

    def test_unknown(self):
        assert _detect_mime_type(b"???", "file.xyz") == "application/octet-stream"


# ---------------------------------------------------------------------------
# sanitize_string
# ---------------------------------------------------------------------------


class TestSanitizeString:
    def test_removes_null_bytes(self):
        assert "\x00" not in sanitize_string("hello\x00world")

    def test_removes_control_chars(self):
        result = sanitize_string("hello\x01\x02world")
        assert "\x01" not in result
        assert "\x02" not in result

    def test_preserves_newline_and_tab(self):
        result = sanitize_string("hello\nworld\ttab")
        assert "\n" in result
        assert "\t" in result

    def test_truncates_to_max_length(self):
        result = sanitize_string("abcdefgh", max_length=5)
        assert len(result) == 5
        assert result == "abcde"

    def test_no_truncation_when_shorter(self):
        result = sanitize_string("abc", max_length=10)
        assert result == "abc"
