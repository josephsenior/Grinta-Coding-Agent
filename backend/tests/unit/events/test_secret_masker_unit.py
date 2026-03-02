"""Tests for backend.events.secret_masker — SecretMasker."""

from backend.events.secret_masker import SecretMasker


class TestSecretMaskerInit:
    def test_empty_secrets(self):
        m = SecretMasker()
        assert m.secrets == {}
        assert m._secret_pattern is None
        assert m._secret_bytes == []


class TestSetSecrets:
    def test_set_secrets(self):
        m = SecretMasker()
        m.set_secrets({"API_KEY": "sk-abc123"})
        assert m.secrets == {"API_KEY": "sk-abc123"}
        assert m._secret_pattern is not None

    def test_set_secrets_copies(self):
        m = SecretMasker()
        original = {"K": "V"}
        m.set_secrets(original)
        original["K2"] = "V2"
        assert "K2" not in m.secrets

    def test_set_secrets_replaces(self):
        m = SecretMasker()
        m.set_secrets({"A": "1"})
        m.set_secrets({"B": "2"})
        assert m.secrets == {"B": "2"}


class TestUpdateSecrets:
    def test_merge(self):
        m = SecretMasker()
        m.set_secrets({"A": "1"})
        m.update_secrets({"B": "2"})
        assert m.secrets == {"A": "1", "B": "2"}


class TestMaskString:
    def test_masks_secret_in_string(self):
        m = SecretMasker()
        m.set_secrets({"KEY": "secret_value"})
        result = m._mask_string("my secret_value here")
        assert "secret_value" not in result
        assert SecretMasker.PLACEHOLDER in result

    def test_no_secrets_returns_original(self):
        m = SecretMasker()
        assert m._mask_string("no secrets") == "no secrets"

    def test_empty_string(self):
        m = SecretMasker()
        m.set_secrets({"K": "V"})
        assert m._mask_string("") == ""

    def test_case_insensitive(self):
        m = SecretMasker()
        m.set_secrets({"KEY": "MySecret"})
        result = m._mask_string("MYSECRET and mysecret")
        assert "MySecret" not in result.lower()
        assert result.count(SecretMasker.PLACEHOLDER) == 2


class TestMaskBytes:
    def test_masks_bytes(self):
        m = SecretMasker()
        m.set_secrets({"KEY": "tokenabc"})
        result = m._mask_bytes(b"header: tokenabc")
        assert b"tokenabc" not in result
        assert SecretMasker.PLACEHOLDER.encode() in result

    def test_no_secrets_returns_original(self):
        m = SecretMasker()
        result = m._mask_bytes(b"data")
        assert result == b"data"

    def test_empty_bytes(self):
        m = SecretMasker()
        m.set_secrets({"K": "V"})
        assert m._mask_bytes(b"") == b""


class TestReplaceSecrets:
    def test_top_level_protected_fields(self):
        """Protected fields at top level should not be masked."""
        m = SecretMasker()
        m.set_secrets({"KEY": "sk123"})
        data = {
            "id": "evt_sk123",
            "timestamp": "2024-sk123",
            "source": "sk123_src",
            "message": "has sk123",
            "content": "also sk123",
        }
        result = m.replace_secrets(data)
        # Protected fields should be unchanged
        assert result["id"] == "evt_sk123"
        assert result["timestamp"] == "2024-sk123"
        assert result["source"] == "sk123_src"
        assert result["message"] == "has sk123"
        # Non-protected field should be masked
        assert "sk123" not in result["content"]

    def test_nested_not_protected(self):
        """Fields in nested dicts should always be masked."""
        m = SecretMasker()
        m.set_secrets({"KEY": "mytoken123"})
        data = {
            "nested": {
                "id": "has mytoken123",
                "message": "has mytoken123 too",
            }
        }
        result = m.replace_secrets(data)
        assert "mytoken123" not in result["nested"]["id"]
        assert "mytoken123" not in result["nested"]["message"]

    def test_list_values(self):
        m = SecretMasker()
        m.set_secrets({"KEY": "tok"})
        data = {"items": ["tok is here", "no match"]}
        result = m.replace_secrets(data)
        assert "tok" not in result["items"][0]
        assert result["items"][1] == "no match"

    def test_tuple_values(self):
        m = SecretMasker()
        m.set_secrets({"KEY": "abc"})
        data = {"vals": ("abc_1", "abc_2")}
        result = m.replace_secrets(data)
        assert isinstance(result["vals"], tuple)
        assert "abc" not in result["vals"][0]
        assert "abc" not in result["vals"][1]

    def test_bytes_values(self):
        m = SecretMasker()
        m.set_secrets({"KEY": "binsecret"})
        data = {"payload": b"data binsecret end"}
        result = m.replace_secrets(data)
        assert b"binsecret" not in result["payload"]

    def test_non_string_value_passthrough(self):
        m = SecretMasker()
        m.set_secrets({"KEY": "x"})
        data = {"count": 42, "flag": True, "empty": None}
        result = m.replace_secrets(data)
        assert result["count"] == 42
        assert result["flag"] is True
        assert result["empty"] is None

    def test_multiple_secrets(self):
        m = SecretMasker()
        m.set_secrets({"A": "alpha", "B": "beta"})
        data = {"text": "alpha and beta are secrets"}
        result = m.replace_secrets(data)
        assert "alpha" not in result["text"]
        assert "beta" not in result["text"]

    def test_empty_secret_value_ignored(self):
        m = SecretMasker()
        m.set_secrets({"EMPTY": "", "REAL": "real_secret"})
        data = {"text": "has real_secret"}
        result = m.replace_secrets(data)
        assert "real_secret" not in result["text"]


class TestRebuildCache:
    def test_empty_secrets_clears_pattern(self):
        m = SecretMasker()
        m.set_secrets({"K": "V"})
        m.set_secrets({})
        assert m._secret_pattern is None
        assert m._secret_bytes == []

    def test_longer_secrets_matched_first(self):
        """Longer secrets should be matched before shorter substrings."""
        m = SecretMasker()
        m.set_secrets({"SHORT": "abc", "LONG": "abcdef"})
        result = m._mask_string("prefix abcdef suffix")
        # The whole "abcdef" should be replaced in one pass
        assert result.count(SecretMasker.PLACEHOLDER) >= 1
        assert "abcdef" not in result
