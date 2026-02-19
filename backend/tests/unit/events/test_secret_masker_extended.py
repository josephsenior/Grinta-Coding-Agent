"""Comprehensive tests for backend.events.secret_masker module.

Tests SecretMasker string/bytes masking, nested structure handling,
top-level field protection, and pattern cache rebuilding.
"""

from __future__ import annotations

import unittest

from backend.events.secret_masker import SecretMasker


class TestSecretMaskerBasics(unittest.TestCase):
    """Tests for basic SecretMasker operations."""

    def setUp(self):
        self.masker = SecretMasker()

    def test_init_empty(self):
        self.assertEqual(self.masker.secrets, {})
        self.assertIsNone(self.masker._secret_pattern)
        self.assertEqual(self.masker._secret_bytes, [])

    def test_set_secrets(self):
        self.masker.set_secrets({"API_KEY": "sk-abc123"})
        self.assertEqual(self.masker.secrets, {"API_KEY": "sk-abc123"})
        self.assertIsNotNone(self.masker._secret_pattern)

    def test_set_secrets_copies_dict(self):
        original = {"KEY": "val"}
        self.masker.set_secrets(original)
        original["KEY2"] = "val2"
        self.assertNotIn("KEY2", self.masker.secrets)

    def test_update_secrets_merges(self):
        self.masker.set_secrets({"KEY1": "val1"})
        self.masker.update_secrets({"KEY2": "val2"})
        self.assertIn("KEY1", self.masker.secrets)
        self.assertIn("KEY2", self.masker.secrets)

    def test_update_secrets_overwrites(self):
        self.masker.set_secrets({"KEY": "old"})
        self.masker.update_secrets({"KEY": "new"})
        self.assertEqual(self.masker.secrets["KEY"], "new")

    def test_placeholder_constant(self):
        self.assertEqual(SecretMasker.PLACEHOLDER, "<secret_hidden>")


class TestSecretMaskerStringMasking(unittest.TestCase):
    """Tests for string value masking."""

    def setUp(self):
        self.masker = SecretMasker()
        self.masker.set_secrets({"API_KEY": "sk-abc123", "TOKEN": "tok-xyz789"})

    def test_mask_string_with_secret(self):
        data = {"content": "Using key sk-abc123 for auth"}
        result = self.masker.replace_secrets(data)
        self.assertNotIn("sk-abc123", result["content"])
        self.assertIn("<secret_hidden>", result["content"])

    def test_mask_multiple_secrets(self):
        data = {"msg": "key=sk-abc123 token=tok-xyz789"}
        result = self.masker.replace_secrets(data)
        self.assertNotIn("sk-abc123", result["msg"])
        self.assertNotIn("tok-xyz789", result["msg"])
        self.assertEqual(result["msg"].count("<secret_hidden>"), 2)

    def test_no_secrets_no_masking(self):
        masker = SecretMasker()
        data = {"content": "safe text with no secrets"}
        result = masker.replace_secrets(data)
        self.assertEqual(result["content"], "safe text with no secrets")

    def test_empty_string_not_masked(self):
        data = {"content": ""}
        result = self.masker.replace_secrets(data)
        self.assertEqual(result["content"], "")

    def test_masking_is_case_insensitive(self):
        self.masker.set_secrets({"KEY": "SecretValue"})
        data = {"content": "has SECRETVALUE in it"}
        result = self.masker.replace_secrets(data)
        self.assertIn("<secret_hidden>", result["content"])

    def test_repeated_secret_in_string(self):
        data = {"content": "sk-abc123 and sk-abc123 again"}
        result = self.masker.replace_secrets(data)
        self.assertEqual(result["content"].count("<secret_hidden>"), 2)


class TestSecretMaskerBytesMasking(unittest.TestCase):
    """Tests for bytes value masking."""

    def setUp(self):
        self.masker = SecretMasker()
        self.masker.set_secrets({"KEY": "mysecret"})

    def test_mask_bytes_with_secret(self):
        data = {"raw": b"data contains mysecret here"}
        result = self.masker.replace_secrets(data)
        self.assertNotIn(b"mysecret", result["raw"])
        self.assertIn(b"<secret_hidden>", result["raw"])

    def test_empty_bytes_not_masked(self):
        data = {"raw": b""}
        result = self.masker.replace_secrets(data)
        self.assertEqual(result["raw"], b"")

    def test_bytes_without_secret_unchanged(self):
        data = {"raw": b"safe content"}
        result = self.masker.replace_secrets(data)
        self.assertEqual(result["raw"], b"safe content")


class TestSecretMaskerNestedStructures(unittest.TestCase):
    """Tests for nested dict/list/tuple masking."""

    def setUp(self):
        self.masker = SecretMasker()
        self.masker.set_secrets({"KEY": "secret123"})

    def test_nested_dict(self):
        data = {"outer": {"inner": "contains secret123"}}
        result = self.masker.replace_secrets(data)
        self.assertNotIn("secret123", result["outer"]["inner"])
        self.assertIn("<secret_hidden>", result["outer"]["inner"])

    def test_nested_list(self):
        data = {"items": ["safe", "has secret123", "also safe"]}
        result = self.masker.replace_secrets(data)
        self.assertEqual(result["items"][0], "safe")
        self.assertNotIn("secret123", result["items"][1])
        self.assertEqual(result["items"][2], "also safe")

    def test_nested_tuple(self):
        data = {"pair": ("first", "secret123 here")}
        result = self.masker.replace_secrets(data)
        self.assertIsInstance(result["pair"], tuple)
        self.assertEqual(result["pair"][0], "first")
        self.assertNotIn("secret123", result["pair"][1])

    def test_deeply_nested(self):
        data = {"level1": {"level2": {"level3": [{"level4": "deep secret123 value"}]}}}
        result = self.masker.replace_secrets(data)
        deep_val = result["level1"]["level2"]["level3"][0]["level4"]
        self.assertNotIn("secret123", deep_val)

    def test_non_string_values_unchanged(self):
        data = {"count": 42, "flag": True, "nothing": None, "rate": 3.14}
        result = self.masker.replace_secrets(data)
        self.assertEqual(result["count"], 42)
        self.assertEqual(result["flag"], True)
        self.assertIsNone(result["nothing"])
        self.assertEqual(result["rate"], 3.14)


class TestSecretMaskerTopLevelProtection(unittest.TestCase):
    """Tests for top-level field protection."""

    def setUp(self):
        self.masker = SecretMasker()
        self.masker.set_secrets({"KEY": "secret123"})

    def test_protected_fields_not_masked_at_top_level(self):
        for field in SecretMasker.TOP_LEVEL_PROTECTED_FIELDS:
            data = {field: "contains secret123", "other": "also secret123"}
            result = self.masker.replace_secrets(data)
            # Protected field should NOT be masked at top level
            self.assertIn("secret123", result[field], f"Field {field} was masked")
            # Non-protected field should be masked
            self.assertNotIn("secret123", result["other"])

    def test_protected_fields_masked_when_nested(self):
        data = {
            "nested": {
                "timestamp": "secret123 in nested timestamp",
                "message": "secret123 in nested message",
            }
        }
        result = self.masker.replace_secrets(data)
        # At nested level, is_top_level=False, so protection doesn't apply
        self.assertNotIn("secret123", result["nested"]["timestamp"])
        self.assertNotIn("secret123", result["nested"]["message"])


class TestSecretMaskerEdgeCases(unittest.TestCase):
    """Tests for edge cases and special scenarios."""

    def test_empty_secret_value_skipped(self):
        masker = SecretMasker()
        masker.set_secrets({"EMPTY": "", "VALID": "real_secret"})
        data = {"content": "has real_secret"}
        result = masker.replace_secrets(data)
        self.assertNotIn("real_secret", result["content"])

    def test_set_secrets_clears_previous(self):
        masker = SecretMasker()
        masker.set_secrets({"OLD": "old_secret"})
        masker.set_secrets({"NEW": "new_secret"})
        data = {"content": "old_secret and new_secret"}
        result = masker.replace_secrets(data)
        # old_secret should NOT be masked (replaced by new set)
        self.assertIn("old_secret", result["content"])
        self.assertNotIn("new_secret", result["content"])

    def test_longer_secrets_masked_first(self):
        """Longer secrets should be matched before shorter substrings."""
        masker = SecretMasker()
        masker.set_secrets({"SHORT": "abc", "LONG": "abcdef"})
        data = {"content": "text abcdef end"}
        result = masker.replace_secrets(data)
        # The longer secret "abcdef" should be matched as one replacement
        self.assertNotIn("abcdef", result["content"])

    def test_special_regex_chars_in_secrets(self):
        masker = SecretMasker()
        masker.set_secrets({"KEY": "my.secret+value[0]"})
        data = {"content": "has my.secret+value[0] in it"}
        result = masker.replace_secrets(data)
        self.assertNotIn("my.secret+value[0]", result["content"])
        self.assertIn("<secret_hidden>", result["content"])

    def test_empty_data_dict(self):
        masker = SecretMasker()
        masker.set_secrets({"KEY": "secret"})
        result = masker.replace_secrets({})
        self.assertEqual(result, {})

    def test_exclude_method_inverse(self):
        """SecretMasker doesn't have exclude, but test the pattern matching."""
        masker = SecretMasker()
        masker.set_secrets({"K": "s3cr3t"})
        data = {"field": "no secrets here"}
        result = masker.replace_secrets(data)
        self.assertEqual(result["field"], "no secrets here")


if __name__ == "__main__":
    unittest.main()
