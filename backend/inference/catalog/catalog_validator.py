"""Validate provider catalog JSON files and model resolution invariants."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.inference.caching.prompt_caching import VALID_PROMPT_CACHE_MODES
from backend.inference.capabilities.model_features import should_support_response_schema
from backend.inference.catalog.catalog_loader import (
    _CATALOG_DIR,
    ModelEntry,
    get_catalog,
    lookup,
    lookup_provider_model,
    runtime_model_id,
    validate_model_transport,
)
from backend.inference.reasoning import (
    WIRE_ANTHROPIC_ADAPTIVE,
    WIRE_ANTHROPIC_EXTENDED,
    WIRE_GEMINI_NATIVE,
    WIRE_GEMINI_OPENAI_COMPAT,
    WIRE_GLM_THINKING,
    WIRE_NONE,
    WIRE_OPENAI_REASONING_EFFORT,
    WIRE_OPENAI_THINKING_AND_EFFORT,
    WIRE_OPENAI_THINKING_ENABLED,
    WIRE_VERCEL_GATEWAY_REASONING,
    supports_reasoning,
)
from backend.inference.reasoning_profiles import tier_order

VALID_REASONING_WIRES: frozenset[str] = frozenset(
    {
        WIRE_NONE,
        WIRE_OPENAI_REASONING_EFFORT,
        WIRE_OPENAI_THINKING_AND_EFFORT,
        WIRE_OPENAI_THINKING_ENABLED,
        WIRE_ANTHROPIC_ADAPTIVE,
        WIRE_ANTHROPIC_EXTENDED,
        WIRE_GEMINI_NATIVE,
        WIRE_GEMINI_OPENAI_COMPAT,
        WIRE_GLM_THINKING,
        WIRE_VERCEL_GATEWAY_REASONING,
    }
)

_VALID_CLIENTS: frozenset[str] = frozenset(
    {
        'openai_compatible',
        'openai_native',
        'anthropic_native',
        'anthropic_compatible',
        'google_native',
        'unsupported',
        'mixed_opencode_surfaces',
        'mixed_opencode_go_surfaces',
    }
)

_TIER_ORDER = set(tier_order())
_ALLOWED_REASONING_TIERS: frozenset[str] = frozenset(_TIER_ORDER) | {'none', 'thinking'}

_NATIVE_REASONING_WIRES: frozenset[str] = frozenset(
    {WIRE_ANTHROPIC_ADAPTIVE, WIRE_ANTHROPIC_EXTENDED, WIRE_GEMINI_NATIVE}
)

# Providers whose catalog models are search/Q&A APIs, not full agent tool hosts.
_SEARCH_ONLY_PROVIDERS: frozenset[str] = frozenset({'perplexity'})


@dataclass(frozen=True, slots=True)
class CatalogValidationIssue:
    provider: str
    model: str | None
    message: str

    def __str__(self) -> str:
        if self.model:
            return f'{self.provider}/{self.model}: {self.message}'
        return f'{self.provider}: {self.message}'


def _as_bool(value: Any) -> bool:
    return bool(value) if isinstance(value, bool) else False


def _validate_runtime_block(
    *,
    provider: str,
    model_name: str,
    runtime: dict[str, Any],
    metadata: dict[str, Any],
) -> list[CatalogValidationIssue]:
    issues: list[CatalogValidationIssue] = []

    if not _as_bool(runtime.get('supports_function_calling', False)):
        if provider not in _SEARCH_ONLY_PROVIDERS:
            issues.append(
                CatalogValidationIssue(
                    provider,
                    model_name,
                    'runtime.supports_function_calling should be true for catalog models',
                )
            )
    elif provider not in _SEARCH_ONLY_PROVIDERS:
        aliases = runtime.get('aliases', [])
        alias_list = aliases if isinstance(aliases, list) else []
        expected_schema = should_support_response_schema(
            model_name,
            provider=provider,
            aliases=[str(alias) for alias in alias_list],
        )
        has_schema = _as_bool(runtime.get('supports_response_schema', False))
        if expected_schema and not has_schema:
            issues.append(
                CatalogValidationIssue(
                    provider,
                    model_name,
                    'supports_response_schema should be true (vendor documents JSON/schema mode)',
                )
            )
        elif has_schema and not expected_schema:
            issues.append(
                CatalogValidationIssue(
                    provider,
                    model_name,
                    'supports_response_schema is true but model is not in documented schema patterns',
                )
            )

    context = runtime.get('context_window_tokens')
    max_in = runtime.get('max_input_tokens')
    max_out = runtime.get('max_output_tokens')
    if (
        isinstance(context, int)
        and isinstance(max_in, int)
        and isinstance(max_out, int)
    ):
        if max_in + max_out > context:
            issues.append(
                CatalogValidationIssue(
                    provider,
                    model_name,
                    'max_input_tokens + max_output_tokens exceeds context_window_tokens',
                )
            )

    wire = runtime.get('reasoning_wire')
    efforts = runtime.get('reasoning_efforts')
    variants = metadata.get('variants') if isinstance(metadata, dict) else None
    has_variants = isinstance(variants, dict) and bool(variants)

    if _as_bool(runtime.get('supports_reasoning_effort', False)):
        if not has_variants and not isinstance(efforts, list):
            issues.append(
                CatalogValidationIssue(
                    provider,
                    model_name,
                    'supports_reasoning_effort requires reasoning_efforts or metadata.variants',
                )
            )
        if isinstance(wire, str) and wire.strip() and wire not in VALID_REASONING_WIRES:
            issues.append(
                CatalogValidationIssue(
                    provider,
                    model_name,
                    f'invalid reasoning_wire {wire!r}',
                )
            )
        if isinstance(efforts, list):
            for effort in efforts:
                if not isinstance(effort, str):
                    continue
                normalized = effort.strip().lower()
                if normalized and normalized not in _ALLOWED_REASONING_TIERS:
                    issues.append(
                        CatalogValidationIssue(
                            provider,
                            model_name,
                            f'reasoning tier {effort!r} is not in tier_order',
                        )
                    )

    if _as_bool(runtime.get('strip_reasoning_effort', False)) and _as_bool(
        runtime.get('supports_reasoning_effort', False)
    ):
        wire = runtime.get('reasoning_wire')
        native_wire = isinstance(wire, str) and wire in _NATIVE_REASONING_WIRES
        if provider != 'anthropic' and not native_wire:
            issues.append(
                CatalogValidationIssue(
                    provider,
                    model_name,
                    'strip_reasoning_effort and supports_reasoning_effort are both true',
                )
            )

    cache_mode = runtime.get('prompt_cache_mode')
    if cache_mode is not None:
        if not isinstance(cache_mode, str):
            issues.append(
                CatalogValidationIssue(
                    provider,
                    model_name,
                    'prompt_cache_mode must be a string',
                )
            )
        elif cache_mode.strip().lower() not in VALID_PROMPT_CACHE_MODES:
            issues.append(
                CatalogValidationIssue(
                    provider,
                    model_name,
                    f'invalid prompt_cache_mode {cache_mode!r}',
                )
            )

    aliases = runtime.get('aliases', [])
    if not isinstance(aliases, list):
        issues.append(
            CatalogValidationIssue(
                provider, model_name, 'runtime.aliases must be a list'
            )
        )
    else:
        prefixed = f'{provider}/{model_name}'
        if prefixed not in aliases and prefixed.lower() not in {
            str(a).lower() for a in aliases
        }:
            issues.append(
                CatalogValidationIssue(
                    provider,
                    model_name,
                    f'missing canonical alias {prefixed!r}',
                )
            )

    return issues


def validate_catalog_file(path: Path) -> list[CatalogValidationIssue]:
    """Validate one catalog JSON file before it is loaded into memory."""
    issues: list[CatalogValidationIssue] = []
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        return [
            CatalogValidationIssue(path.stem, None, f'invalid JSON: {exc}'),
        ]

    provider = str(raw.get('provider') or path.stem).strip().lower()
    if not provider:
        return [CatalogValidationIssue(path.stem, None, 'missing provider id')]

    if provider != path.stem:
        issues.append(
            CatalogValidationIssue(
                provider,
                None,
                f'file name {path.stem!r} does not match provider {provider!r}',
            )
        )

    client = raw.get('client')
    if isinstance(client, str) and client not in _VALID_CLIENTS:
        issues.append(
            CatalogValidationIssue(
                provider,
                None,
                f'client must be one of {_VALID_CLIENTS}, got {client!r}',
            )
        )

    models = raw.get('models')
    if not isinstance(models, dict) or not models:
        issues.append(
            CatalogValidationIssue(provider, None, 'models must be a non-empty object')
        )
        return issues

    seen_names: set[str] = set()
    for model_name, info in models.items():
        if model_name in seen_names:
            issues.append(
                CatalogValidationIssue(provider, model_name, 'duplicate model name')
            )
        seen_names.add(model_name)

        if not isinstance(info, dict):
            issues.append(
                CatalogValidationIssue(
                    provider, model_name, 'model entry must be an object'
                )
            )
            continue

        runtime = info.get('runtime')
        if not isinstance(runtime, dict):
            issues.append(
                CatalogValidationIssue(provider, model_name, "missing 'runtime' object")
            )
            continue

        metadata = info.get('metadata')
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            issues.append(
                CatalogValidationIssue(
                    provider, model_name, 'metadata must be an object'
                )
            )
            metadata = {}

        declared = str(runtime.get('provider') or provider).strip().lower()
        if declared != provider:
            issues.append(
                CatalogValidationIssue(
                    provider,
                    model_name,
                    f'runtime.provider {declared!r} != file provider {provider!r}',
                )
            )

        issues.extend(
            _validate_runtime_block(
                provider=provider,
                model_name=model_name,
                runtime=runtime,
                metadata=metadata,
            )
        )

    return issues


def _validate_entry_resolution(entry: ModelEntry) -> list[CatalogValidationIssue]:
    issues: list[CatalogValidationIssue] = []
    provider = entry.provider
    name = entry.name

    exact = lookup_provider_model(provider, name, allow_aliases=False)
    if exact is None or exact.name != name or exact.provider != provider:
        issues.append(
            CatalogValidationIssue(
                provider,
                name,
                'lookup_provider_model(provider, name) failed',
            )
        )

    prefixed = lookup(f'{provider}/{name}')
    if prefixed is None or prefixed.name != name or prefixed.provider != provider:
        issues.append(
            CatalogValidationIssue(
                provider,
                name,
                f"lookup('{provider}/{name}') failed",
            )
        )

    for alias in entry.aliases:
        alias_str = str(alias).strip()
        if not alias_str:
            continue
        if alias_str.startswith(f'{provider}/'):
            resolved = lookup(alias_str)
        else:
            resolved = lookup_provider_model(provider, alias_str, allow_aliases=True)
        if resolved is None or resolved.name != name or resolved.provider != provider:
            issues.append(
                CatalogValidationIssue(
                    provider,
                    name,
                    f'alias {alias_str!r} does not resolve to this entry',
                )
            )

    try:
        validate_model_transport(f'{provider}/{name}', config_provider=provider)
    except Exception as exc:
        issues.append(
            CatalogValidationIssue(
                provider,
                name,
                f'transport validation failed: {exc}',
            )
        )

    if supports_reasoning(entry) and not entry.reasoning_efforts:
        metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
        if not metadata.get('variants'):
            issues.append(
                CatalogValidationIssue(
                    provider,
                    name,
                    'supports reasoning but has no reasoning_efforts or variants',
                )
            )

    return issues


def validate_loaded_catalog() -> list[CatalogValidationIssue]:
    """Validate resolution and runtime invariants for loaded catalog entries."""
    issues: list[CatalogValidationIssue] = []
    entries = get_catalog()

    for entry in entries:
        issues.extend(_validate_entry_resolution(entry))

    from backend.inference.catalog.provider_catalog import (
        LOCAL_PROVIDERS,
        build_model_entries_by_provider,
        get_provider_ids,
        list_model_names,
    )

    catalog_by_provider: dict[str, list[ModelEntry]] = {}
    for entry in entries:
        catalog_by_provider.setdefault(entry.provider, []).append(entry)

    for provider in sorted(get_provider_ids()):
        if provider in LOCAL_PROVIDERS:
            continue
        if provider not in catalog_by_provider:
            issues.append(
                CatalogValidationIssue(
                    provider,
                    None,
                    'configured provider has no catalog file',
                )
            )
            continue

        listed = set(list_model_names(provider))
        for entry in catalog_by_provider[provider]:
            model_id = runtime_model_id(entry)
            if model_id not in listed:
                issues.append(
                    CatalogValidationIssue(
                        provider,
                        entry.name,
                        f'model {model_id!r} missing from list_model_names()',
                    )
                )

        picker = build_model_entries_by_provider(provider=provider).get(provider, [])
        picker_names = {item.name for item in picker}
        for entry in catalog_by_provider[provider]:
            if entry.name not in picker_names:
                issues.append(
                    CatalogValidationIssue(
                        provider,
                        entry.name,
                        'model missing from build_model_entries_by_provider()',
                    )
                )

    return issues


def validate_all_catalogs() -> list[CatalogValidationIssue]:
    """Validate every catalog file on disk and loaded resolution invariants."""
    issues: list[CatalogValidationIssue] = []
    for path in sorted(_CATALOG_DIR.glob('*.json')):
        issues.extend(validate_catalog_file(path))
    issues.extend(validate_loaded_catalog())
    return issues
