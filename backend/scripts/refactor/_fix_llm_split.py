"""Fix llm_* split files: single docstring, __future__ first."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
parent = REPO / 'backend/inference'
doc = (
    'Split from ``llm.py`` — see ``backend.inference.llm`` facade.'
)

for name in ('llm_exceptions.py', 'llm_stream.py', 'llm_config.py', 'llm_core.py'):
    path = parent / name
    text = path.read_text(encoding='utf-8')
    # Drop duplicated leading docstrings; keep from first __future__ onward
    idx = text.find('from __future__ import annotations')
    if idx == -1:
        raise RuntimeError(f'no future import in {name}')
    body_after_imports = text[idx:]
    path.write_text(f'"""{doc}"""\n\n' + body_after_imports, encoding='utf-8')
    print('fixed', name)

# Re-apply core cross-imports
core_path = parent / 'llm_core.py'
core = core_path.read_text(encoding='utf-8')
extra = '''
from backend.inference.llm.config import (
    _apply_base_url_discovery,
    _apply_custom_tokenizer,
    _get_provider_resolver,
    _load_cached_features,
    _llm_model_metadata_for_log,
    _resolve_function_calling_config,
    _safe_call_kwargs_for_log,
    _validate_api_key_or_local,
)
from backend.inference.llm.exceptions import _map_provider_exception
from backend.inference.llm.stream import (
    LLM_RETRY_EXCEPTIONS,
    _INBAND_DISCONNECT_PHRASES,
    _INBAND_PREFIX_LIMIT,
    _stream_with_chunk_timeout,
)
'''
marker = 'if TYPE_CHECKING:\n    from backend.core.config import LLMConfig\n'
if marker in core and 'from backend.inference.llm.config import' not in core:
    core = core.replace(marker, marker + extra)
    core_path.write_text(core, encoding='utf-8')
    print('fixed llm_core cross-imports')
