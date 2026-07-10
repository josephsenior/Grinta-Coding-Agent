"""Integrity checks for inference catalog JSON files and model resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.inference.catalog.catalog_loader import (
    get_catalog,
    get_models_for_provider,
    lookup,
    lookup_provider_model,
)
from backend.inference.catalog.catalog_validator import (
    validate_all_catalogs,
    validate_catalog_file,
    validate_loaded_catalog,
)
from backend.inference.catalog.provider_catalog import (
    LOCAL_PROVIDERS,
    build_model_entries_by_provider,
    get_listable_providers,
    get_provider_ids,
    list_model_names,
)

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


def test_each_catalog_file_passes_schema_validation(catalog_path: Path) -> None:
    issues = validate_catalog_file(catalog_path)
    assert not issues, '\n'.join(str(issue) for issue in issues)


def test_all_catalogs_pass_full_validation() -> None:
    issues = validate_all_catalogs()
    assert not issues, '\n'.join(str(issue) for issue in issues[:20])


def test_get_catalog_loads_all_providers_without_error() -> None:
    entries = get_catalog()
    assert len(entries) >= 100
    providers = {entry.provider for entry in entries}
    assert 'openai' in providers
    assert 'anthropic' in providers
    assert 'digitalocean' in providers
    assert 'together' in providers


def test_every_configured_hosted_provider_has_catalog_file() -> None:
    catalog_providers = {path.stem for path in _CATALOG_DIR.glob('*.json')}
    missing = sorted(
        provider
        for provider in get_provider_ids()
        if provider not in LOCAL_PROVIDERS and provider not in catalog_providers
    )
    assert not missing, f'missing catalog files for: {missing}'


def test_listable_hosted_providers_have_catalog_models() -> None:
    for provider in get_listable_providers():
        if provider in LOCAL_PROVIDERS:
            continue
        models = get_models_for_provider(provider)
        assert models, f'listable hosted provider {provider!r} has no catalog models'


def test_reasoning_models_declare_catalog_efforts() -> None:
    missing: list[str] = []
    for entry in get_catalog():
        if not entry.supports_reasoning_effort:
            continue
        if entry.reasoning_efforts or (
            isinstance(entry.metadata, dict) and entry.metadata.get('variants')
        ):
            continue
        missing.append(f'{entry.provider}/{entry.name}')
    assert not missing, (
        'reasoning-capable catalog models must declare runtime.reasoning_efforts '
        f'or metadata.variants: {missing[:5]}'
    )


@pytest.mark.parametrize(
    ('provider', 'model_id'),
    [
        ('groq', 'meta-llama/llama-4-scout-17b-16e-instruct'),
        ('groq', 'meta-llama/llama-4-scout'),
        ('openai', 'gpt-5'),
        ('anthropic', 'claude-sonnet-4-6'),
        ('google', 'gemini-3-flash'),
        ('digitalocean', 'deepseek-v4-pro'),
        ('together', 'meta-llama/Llama-3.3-70B-Instruct-Turbo'),
        ('lightning', 'meta-llama/Meta-Llama-3.1-8B-Instruct'),
        ('openrouter', 'anthropic/claude-sonnet-4'),
        ('vercel', 'anthropic/claude-opus-4.8'),
        ('vercel', 'openai/gpt-5.5'),
        ('vercel', 'openai/gpt-5.6'),
        ('vercel', 'google/gemini-3.5-flash'),
        ('opencode', 'gpt-5'),
        ('opencode', 'gpt-5.6'),
        ('opencode', 'gemini-3-flash'),
        ('openai', 'gpt-5.6'),
    ],
)
def test_canonical_model_ids_resolve(provider: str, model_id: str) -> None:
    entry = lookup_provider_model(provider, model_id, allow_aliases=True)
    assert entry is not None
    assert entry.provider == provider
    assert lookup(f'{provider}/{model_id}') is not None


def test_groq_onboarding_default_resolves() -> None:
    entry = lookup('groq/meta-llama/llama-4-scout')
    assert entry is not None
    assert entry.provider == 'groq'
    assert 'scout' in entry.name.lower()


def test_loaded_catalog_resolution_invariants() -> None:
    issues = validate_loaded_catalog()
    assert not issues, '\n'.join(str(issue) for issue in issues[:20])


def test_build_model_entries_includes_all_catalog_models() -> None:
    for provider in get_provider_ids():
        if provider in LOCAL_PROVIDERS:
            continue
        catalog_names = {
            entry.name for entry in get_catalog() if entry.provider == provider
        }
        if not catalog_names:
            continue
        picker_names = {
            entry.name
            for entry in build_model_entries_by_provider(provider=provider).get(
                provider, []
            )
        }
        missing = sorted(catalog_names - picker_names)
        assert not missing, f'{provider} picker missing: {missing[:5]}'


def test_all_opencode_catalog_models_have_grinta_transport() -> None:
    from backend.inference.catalog.catalog_loader import validate_model_transport

    blocked: list[str] = []
    for entry in get_catalog():
        if entry.provider != 'opencode':
            continue
        try:
            validate_model_transport(
                f'opencode/{entry.name}', config_provider='opencode'
            )
        except Exception as exc:
            blocked.append(f'{entry.name}: {exc}')
    assert not blocked, blocked


def test_list_model_names_includes_all_catalog_models() -> None:
    for provider in get_provider_ids():
        if provider in LOCAL_PROVIDERS:
            continue
        listed = set(list_model_names(provider))
        for entry in get_catalog():
            if entry.provider != provider:
                continue
            assert entry.name in listed, (
                f'{provider}/{entry.name} missing from list_model_names()'
            )
