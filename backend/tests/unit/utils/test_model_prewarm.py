from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from backend.utils import model_prewarm


def test_get_default_models_to_prewarm_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('EMBEDDING_MODEL', raising=False)
    monkeypatch.delenv('RERANKER_MODEL', raising=False)
    monkeypatch.delenv('PREBUNDLED_MODELS', raising=False)

    models = model_prewarm.get_default_models_to_prewarm()

    assert models[0] == 'nomic-ai/nomic-embed-text-v1.5'
    assert models[1] == 'cross-encoder/ms-marco-MiniLM-L-6-v2'


def test_get_default_models_to_prewarm_env_and_dedup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('EMBEDDING_MODEL', 'emb/x')
    monkeypatch.setenv('RERANKER_MODEL', 'rer/y')
    monkeypatch.setenv('PREBUNDLED_MODELS', 'emb/x, extra/z , rer/y')

    models = model_prewarm.get_default_models_to_prewarm()

    assert models == ['emb/x', 'rer/y', 'extra/z']


def test_ensure_models_available_raises_when_snapshot_missing() -> None:
    with patch('backend.utils.model_prewarm.snapshot_download', None):
        with pytest.raises(RuntimeError):
            model_prewarm.ensure_models_available(['a/b'], fail_on_missing=True)


def test_ensure_models_available_returns_empty_when_snapshot_missing_nonfatal() -> None:
    with patch('backend.utils.model_prewarm.snapshot_download', None):
        result = model_prewarm.ensure_models_available(['a/b'], fail_on_missing=False)
    assert result == {}


def test_ensure_models_available_success_sets_offline_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('HF_HUB_OFFLINE', raising=False)
    monkeypatch.delenv('TRANSFORMERS_OFFLINE', raising=False)

    def _fake_snapshot_download(*, repo_id: str, local_files_only: bool) -> str:
        assert local_files_only is True
        return f'/cache/{repo_id}'

    with patch(
        'backend.utils.model_prewarm.snapshot_download',
        side_effect=_fake_snapshot_download,
    ):
        result = model_prewarm.ensure_models_available(['m/one', 'm/two'])

    assert result == {'m/one': '/cache/m/one', 'm/two': '/cache/m/two'}
    assert os.environ.get('HF_HUB_OFFLINE') == '1'
    assert os.environ.get('TRANSFORMERS_OFFLINE') == '1'


def test_ensure_models_available_raises_on_missing_model() -> None:
    def _fake_snapshot_download(*, repo_id: str, local_files_only: bool) -> str:
        raise FileNotFoundError(repo_id)

    with patch(
        'backend.utils.model_prewarm.snapshot_download',
        side_effect=_fake_snapshot_download,
    ):
        with pytest.raises(RuntimeError) as exc:
            model_prewarm.ensure_models_available(
                ['missing/repo'], fail_on_missing=True
            )
    assert 'missing/repo' in str(exc.value)
