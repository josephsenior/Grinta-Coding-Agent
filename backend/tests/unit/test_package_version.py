"""Unit tests for package version resolution."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

import pytest

import backend


def test_get_version_prefers_pyproject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend, '_version_from_pyproject', lambda: '9.8.7')
    monkeypatch.setattr(backend, '_version_from_metadata', lambda: '1.2.3')
    assert backend.get_version() == '9.8.7'


def test_get_version_falls_back_to_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend, '_version_from_pyproject', lambda: None)
    monkeypatch.setattr(backend, '_version_from_metadata', lambda: '1.2.3')
    assert backend.get_version() == '1.2.3'


def test_get_version_default_when_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend, '_version_from_pyproject', lambda: None)
    monkeypatch.setattr(backend, '_version_from_metadata', lambda: None)
    assert backend.get_version() == backend._DEFAULT_VERSION


def test_version_from_metadata_handles_missing_package() -> None:
    with patch('backend.version', side_effect=PackageNotFoundError()):
        assert backend._version_from_metadata() is None


def test_version_from_pyproject_reads_local_pyproject() -> None:
    result = backend._version_from_pyproject()
    assert result is not None
    assert result == backend.get_version() or result.count('.') >= 1


def test_package_exports() -> None:
    assert backend.__package_name__ == 'grinta'
    assert isinstance(backend.__version__, str)
    assert backend.get_version()
