"""Model capability detection helpers used to gate Grinta LLM features."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch


def normalize_model_name(model: str) -> str:
    """Normalize a model string to a canonical, comparable name.

    Strategy:
    - Trim whitespace
    - Lowercase
    - If there is a '/', keep only the basename after the last '/'
      (handles prefixes like openai/, anthropic/, etc.)
      and treat ':' inside that basename as an Ollama-style variant tag to be removed
    - There is no provider:model form; providers, when present, use 'provider/model'
    - Drop a trailing "-gguf" suffix if present
    """
    raw = (model or '').strip().lower()
    if '/' in raw:
        name = raw.split('/')[-1]
        if ':' in name:
            name = name.split(':', 1)[0]
    else:
        name = raw
    return name.removesuffix('-gguf')


def model_matches(model: str, patterns: list[str]) -> bool:
    """Return True if the model matches any of the glob patterns.

    If a pattern contains a '/', it is treated as provider-qualified and matched
    against the full, lowercased model string (including provider prefix).
    Otherwise, it is matched against the normalized basename.
    """
    raw = (model or '').strip().lower()
    name = normalize_model_name(model)
    for pat in patterns:
        pat_l = pat.lower()
        if ('/' in pat_l and fnmatch(raw, pat_l)) or (
            '/' not in pat_l and fnmatch(name, pat_l)
        ):
            return True
    return False


from backend.inference.capabilities import ModelCapabilities  # noqa: E402


@dataclass(frozen=True)
class ModelFeatures(ModelCapabilities):
    """Capabilities and limits reported for a particular LLM provider/model pair."""

    context_window_tokens: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None


FUNCTION_CALLING_PATTERNS: list[str] = [
    'claude-opus-4*',
    'claude-sonnet-4*',
    'claude-haiku-4*',
    'claude-4*',
    'gpt-4o*',
    'gpt-4.1*',
    'gpt-4*',
    'gpt-5*',
    'o1-*',
    'o3-*',
    'o4-*',
    'google/gemini-2.5-*',
    'google/gemini-3*',
    'gemini-2.5-*',
    'gemini-3*',
    'grok-*',
    'kimi-k2*',
    'qwen3*',
    'zai-glm-4.7*',
    'zai-glm-5*',
    'glm-5*',
    'deepseek*',
]
REASONING_EFFORT_PATTERNS: list[str] = [
    'o1-*',
    'o3-*',
    'o4-*',
    'gemini-2.5-*',
    'gemini-3*',
    'gpt-5*',
    'deepseek*',
]
PROMPT_CACHE_PATTERNS: list[str] = [
    'claude-opus-4*',
    'claude-sonnet-4*',
    'claude-haiku-4*',
    'claude-4*',
    'deepseek*',
    # Google Gemini explicit context cache (see GeminiClient + gemini_cache)
    'google/gemini-2.5-*',
    'google/gemini-3*',
    'gemini-2.5-*',
    'gemini-3*',
]
SUPPORTS_STOP_WORDS_FALSE_PATTERNS: list[str] = [
    'o1*',
    'xai/grok-4*',
    'deepseek*',
]


RESPONSE_SCHEMA_PATTERNS: list[str] = [
    'gpt-4o*',
    'gpt-4-turbo*',
    'gpt-4.1*',
    'gpt-5*',
    'o1-*',
    'o3-*',
    'o4-*',
    'google/gemini-2.5-*',
    'google/gemini-3*',
    'gemini-3*',
    'claude-opus-4*',
    'claude-sonnet-4*',
    'claude-haiku-4*',
    'claude-4*',
]


def get_model_token_limits(model: str) -> tuple[int | None, int | None]:
    """Get max input and output token limits for a model."""
    from backend.inference.catalog_loader import get_token_limits

    return get_token_limits(model)


def get_features(model: str) -> ModelFeatures:
    """Get feature capabilities for a specific model.

    Catalog entries are the source of truth. Uncataloged models receive
    conservative defaults suitable for local/manual ids.
    """
    from backend.inference.catalog_loader import lookup
    from backend.inference.context_limits import derive_usable_input_tokens

    if entry := lookup(model):
        usable_input = derive_usable_input_tokens(
            context_window_tokens=getattr(entry, 'context_window_tokens', None),
            max_output_tokens=entry.max_output_tokens,
            fallback_input_tokens=entry.max_input_tokens,
        )
        return ModelFeatures(
            context_window_tokens=getattr(entry, 'context_window_tokens', None),
            max_input_tokens=usable_input,
            max_output_tokens=entry.max_output_tokens,
            supports_function_calling=entry.supports_function_calling,
            supports_reasoning_effort=entry.supports_reasoning_effort,
            supports_prompt_cache=entry.supports_prompt_cache,
            supports_stop_words=entry.supports_stop_words,
            supports_response_schema=entry.supports_response_schema,
        )

    max_input, max_output = get_model_token_limits(model)
    return ModelFeatures(
        context_window_tokens=None,
        max_input_tokens=max_input,
        max_output_tokens=max_output,
        supports_function_calling=True,
        supports_reasoning_effort=False,
        supports_prompt_cache=False,
        supports_stop_words=True,
        supports_response_schema=False,
    )
