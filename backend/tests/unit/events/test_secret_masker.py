"""Unit tests for backend.events.secret_masker — recursive secret redaction."""

from __future__ import annotations

import pytest

from backend.events.secret_masker import SecretMasker


# ---------------------------------------------------------------------------
# Construction & set/update secrets
# ---------------------------------------------------------------------------


class TestSecretMaskerInit:
    def test_initial_state(self):
        m = SecretMasker()
        assert m.secrets == {}
        assert m._secret_pattern is None
        assert m._secret_bytes == []

    def test_set_secrets(self):
        m = SecretMasker()
        m.set_secrets({"KEY": "abc123"})
        assert m.secrets == {"KEY": "abc123"}
        assert m._secret_pattern is not None

    def test_set_secrets_replaces_old(self):
        m = SecretMasker()
        m.set_secrets({"A": "aaa"})
        m.set_secrets({"B": "bbb"})
        assert "A" not in m.secrets
        assert m.secrets["B"] == "bbb"

    def test_update_secrets_merges(self):
        m = SecretMasker()
        m.set_secrets({"A": "aaa"})
        m.update_secrets({"B": "bbb"})
        assert m.secrets == {"A": "aaa", "B": "bbb"}

    def test_set_secrets_copies_dict(self):
        """Caller's dict mutation should not affect the masker."""
        m = SecretMasker()
        d = {"X": "secret"}
        m.set_secrets(d)
        d["Y"] = "another"
        assert "Y" not in m.secrets

    def test_empty_values_skipped(self):
        m = SecretMasker()
        m.set_secrets({"EMPTY": "", "GOOD": "token"})
        # Pattern built only from non-empty values
        assert m._secret_pattern is not None
        assert m._mask_string("token") == SecretMasker.PLACEHOLDER
        assert m._mask_string("") == ""


# ---------------------------------------------------------------------------
# String masking
# ---------------------------------------------------------------------------


class TestStringMasking:
    @pytest.fixture(autouse=True)
    def masker(self):
        self.m = SecretMasker()
        self.m.set_secrets({"API_KEY": "sk-12345", "DB_PASS": "hunter2"})

    def test_basic_replacement(self):
        assert self.m._mask_string("my key: sk-12345") == f"my key: {SecretMasker.PLACEHOLDER}"

    def test_multiple_occurrences(self):
        result = self.m._mask_string("sk-12345 and sk-12345 again")
        assert result.count(SecretMasker.PLACEHOLDER) == 2
        assert "sk-12345" not in result

    def test_multiple_different_secrets(self):
        result = self.m._mask_string("key=sk-12345 pass=hunter2")
        assert "sk-12345" not in result
        assert "hunter2" not in result

    def test_no_match(self):
        assert self.m._mask_string("nothing here") == "nothing here"

    def test_case_insensitive(self):
        """Regex is compiled with re.IGNORECASE."""
        result = self.m._mask_string("SK-12345 is same as sk-12345")
        assert "SK-12345" not in result

    def test_empty_string(self):
        assert self.m._mask_string("") == ""

    def test_no_secrets_configured(self):
        m2 = SecretMasker()
        assert m2._mask_string("sk-12345") == "sk-12345"

    def test_special_regex_chars_in_secret(self):
        """Secrets with regex-special chars must be escaped properly."""
        m = SecretMasker()
        m.set_secrets({"REGEX_KEY": "abc.+*?$[]()"})
        assert m._mask_string("found abc.+*?$[]() here") == f"found {SecretMasker.PLACEHOLDER} here"


# ---------------------------------------------------------------------------
# Byte masking
# ---------------------------------------------------------------------------


class TestByteMasking:
    def test_basic_bytes(self):
        m = SecretMasker()
        m.set_secrets({"KEY": "tok_xr9"})
        result = m._mask_bytes(b"the tok_xr9 value")
        assert b"tok_xr9" not in result
        assert SecretMasker.PLACEHOLDER.encode() in result

    def test_no_match_bytes(self):
        m = SecretMasker()
        m.set_secrets({"KEY": "xyz"})
        assert m._mask_bytes(b"nothing") == b"nothing"

    def test_empty_bytes(self):
        m = SecretMasker()
        m.set_secrets({"KEY": "xyz"})
        assert m._mask_bytes(b"") == b""

    def test_no_secrets_bytes(self):
        m = SecretMasker()
        assert m._mask_bytes(b"data") == b"data"


# ---------------------------------------------------------------------------
# Recursive replacement (replace_secrets)
# ---------------------------------------------------------------------------


class TestReplaceSecrets:
    @pytest.fixture(autouse=True)
    def masker(self):
        self.m = SecretMasker()
        self.m.set_secrets({"TOKEN": "tok_abc"})

    def test_top_level_string_value(self):
        data = {"content": "prefix tok_abc suffix"}
        result = self.m.replace_secrets(data)
        assert "tok_abc" not in result["content"]

    def test_nested_dict(self):
        data = {"extras": {"inner": "tok_abc"}}
        result = self.m.replace_secrets(data)
        assert "tok_abc" not in result["extras"]["inner"]

    def test_nested_list(self):
        data = {"items": ["tok_abc", "safe"]}
        result = self.m.replace_secrets(data)
        assert "tok_abc" not in result["items"][0]
        assert result["items"][1] == "safe"

    def test_nested_tuple(self):
        data = {"pair": ("tok_abc", 42)}
        result = self.m.replace_secrets(data)
        assert isinstance(result["pair"], tuple)
        assert "tok_abc" not in result["pair"][0]
        assert result["pair"][1] == 42

    def test_bytes_inside_dict(self):
        data = {"raw": b"tok_abc binary"}
        result = self.m.replace_secrets(data)
        assert b"tok_abc" not in result["raw"]

    def test_non_string_values_pass_through(self):
        data = {"count": 42, "flag": True, "nothing": None}
        result = self.m.replace_secrets(data)
        assert result == {"count": 42, "flag": True, "nothing": None}

    def test_deeply_nested(self):
        data = {"a": {"b": {"c": {"d": "tok_abc"}}}}
        result = self.m.replace_secrets(data)
        assert "tok_abc" not in result["a"]["b"]["c"]["d"]


# ---------------------------------------------------------------------------
# Top-level protected fields
# ---------------------------------------------------------------------------


class TestProtectedFields:
    def test_protected_fields_not_masked(self):
        m = SecretMasker()
        m.set_secrets({"TOKEN": "tok_abc"})
        data = {
            "id": "tok_abc",
            "source": "tok_abc",
            "timestamp": "tok_abc",
            "cause": "tok_abc",
            "action": "tok_abc",
            "observation": "tok_abc",
            "message": "tok_abc",
            "content": "tok_abc",  # NOT protected
        }
        result = m.replace_secrets(data, is_top_level=True)
        for key in SecretMasker.TOP_LEVEL_PROTECTED_FIELDS:
            assert result[key] == "tok_abc", f"Protected field {key!r} was masked"
        # content IS masked
        assert result["content"] == SecretMasker.PLACEHOLDER

    def test_nested_dict_not_protected(self):
        """Protected-field check only applies at is_top_level=True."""
        m = SecretMasker()
        m.set_secrets({"TOKEN": "tok_abc"})
        data = {"nested": {"id": "tok_abc"}}
        result = m.replace_secrets(data)
        # 'id' in a nested dict should be masked
        assert result["nested"]["id"] == SecretMasker.PLACEHOLDER


# ---------------------------------------------------------------------------
# Edge cases & unicode
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_overlapping_secrets_longer_first(self):
        """Longer secret patterns should be matched preferentially."""
        m = SecretMasker()
        m.set_secrets({"SHORT": "abc", "LONG": "abcdef"})
        # The regex is sorted by length descending, so "abcdef" matches first
        result = m._mask_string("xabcdefx")
        # Should replace "abcdef" as one unit, not "abc" + "def"
        assert result.count(SecretMasker.PLACEHOLDER) == 1

    def test_unicode_secret(self):
        m = SecretMasker()
        m.set_secrets({"UNI": "пароль"})
        result = m._mask_string("your пароль is leaked")
        assert "пароль" not in result
        assert SecretMasker.PLACEHOLDER in result

    def test_unicode_bytes(self):
        m = SecretMasker()
        m.set_secrets({"UNI": "пароль"})
        result = m._mask_bytes("your пароль is leaked".encode())
        assert "пароль".encode() not in result

    def test_newline_in_secret(self):
        m = SecretMasker()
        m.set_secrets({"NL": "line1\nline2"})
        result = m._mask_string("found line1\nline2 here")
        assert "line1\nline2" not in result

    def test_very_long_secret(self):
        m = SecretMasker()
        secret = "x" * 10_000
        m.set_secrets({"BIG": secret})
        result = m._mask_string(f"prefix {secret} suffix")
        assert secret not in result

    def test_replace_secrets_returns_same_dict(self):
        """replace_secrets mutates in-place and returns the same dict object."""
        m = SecretMasker()
        m.set_secrets({"K": "val"})
        data = {"a": "val"}
        result = m.replace_secrets(data)
        assert result is data

    def test_non_string_secret_value_ignored(self):
        """Non-string values in the secrets dict are skipped."""
        m = SecretMasker()
        m.set_secrets({"NUM": 12345, "STR": "real"})  # type: ignore[dict-item]
        assert m._mask_string("real 12345") == f"{SecretMasker.PLACEHOLDER} 12345"
