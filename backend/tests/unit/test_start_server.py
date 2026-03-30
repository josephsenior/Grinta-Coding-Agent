"""Unit tests for start_server module helpers."""

from __future__ import annotations

import pytest

from start_server import validate_storage_contract


def test_validate_storage_contract_allows_file_mode(monkeypatch):
    monkeypatch.setenv("APP_KB_STORAGE_TYPE", "file")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    validate_storage_contract()


def test_validate_storage_contract_requires_database_url(monkeypatch):
    monkeypatch.setenv("APP_KB_STORAGE_TYPE", "database")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as exc:
        validate_storage_contract()
    assert exc.value.code == 2


def test_validate_storage_contract_accepts_database_with_url(monkeypatch):
    monkeypatch.setenv("APP_KB_STORAGE_TYPE", "database")
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:app_dev@postgres:5432/app")
    validate_storage_contract()
