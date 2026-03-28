"""Regression tests for secret masking (literal token replacement)."""

from __future__ import annotations

from backend.ledger.secret_masker import SecretMasker


def test_masks_configured_secret_in_string() -> None:
    m = SecretMasker()
    m.set_secrets({"K": "sk-secret-token"})
    out = m.replace_secrets({"text": "prefix sk-secret-token suffix"}, is_top_level=False)
    assert out["text"] == "prefix <secret_hidden> suffix"


def test_top_level_id_field_not_recursed_so_unchanged() -> None:
    """Protected top-level keys are skipped entirely (event envelope)."""
    m = SecretMasker()
    m.set_secrets({"K": "sk-xyz"})
    data = {"id": "sk-xyz", "extra": "sk-xyz tail"}
    out = m.replace_secrets(data, is_top_level=True)
    assert out["id"] == "sk-xyz"
    assert out["extra"] == "<secret_hidden> tail"
