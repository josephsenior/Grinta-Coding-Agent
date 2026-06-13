"""Integrity checks for inference catalog and param profile data files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.inference.catalog_loader import get_catalog, get_models_for_provider
from backend.inference.param_profiles import _load_profile_data
from backend.inference.registry import LOCAL_PROVIDERS, get_listable_providers

_CATALOG_DIR = Path(__file__).resolve().parents[3] / 'inference' / 'catalogs'


@pytest.fixture(params=sorted(_CATALOG_DIR.glob('*.json')), ids=lambda p: p.stem)
def catalog_path(request: pytest.FixtureRequest) -> Path:
    return request.param


def test_each_catalog_file_is_valid_json_with_models(catalog_path: Path) -> None:
    raw = json.loads(catalog_path.read_text(encoding='utf-8'))
    provider = str(raw.get('provider') or catalog_path.stem).strip().lower()
    assert provider, f'{catalog_path.name} must declare a provider'
    models = raw.get('models')
    assert isinstance(models, dict) and models, (
        f'{catalog_path.name} must contain a non-empty models object'
    )


def test_get_catalog_loads_all_providers_without_error() -> None:
    entries = get_catalog()
    assert len(entries) >= 20
    providers = {entry.provider for entry in entries}
    assert 'openai' in providers
    assert 'anthropic' in providers


def test_listable_hosted_providers_have_catalog_models() -> None:
    for provider in get_listable_providers():
        if provider in LOCAL_PROVIDERS:
            continue
        models = get_models_for_provider(provider)
        assert models, f'listable hosted provider {provider!r} has no catalog models'


def test_param_profiles_json_loads() -> None:
    data = _load_profile_data()
    profiles = data.get('profiles')
    assert isinstance(profiles, dict) and profiles
    defaults = data.get('provider_defaults')
    assert isinstance(defaults, dict) and defaults
