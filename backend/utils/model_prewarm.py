"""Model prewarm utilities for required Hugging Face repos.

This module ensures required models are available in the local HF cache (snapshot)
and provides a small helper used by the FastAPI startup lifespan to fail fast when
prebundled models are missing.

It intentionally runs huggingface_hub.snapshot_download with local_files_only=True
so the runtime never performs network downloads at user-facing time.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

snapshot_download: Any
try:
    from huggingface_hub import snapshot_download as _snapshot_download
except Exception as e:  # pragma: no cover - defensive (tests may not have hf_hub)
    snapshot_download = None
    logger.debug('huggingface_hub.snapshot_download unavailable: %s', e)
else:
    snapshot_download = _snapshot_download


def get_default_models_to_prewarm() -> List[str]:
    """Return the default list of model repo ids to prewarm.

    Reads common env vars and falls back to sensible defaults used elsewhere in
    the codebase.
    """
    models: List[str] = []
    emb = os.getenv('EMBEDDING_MODEL')
    if emb:
        models.append(emb)
    else:
        models.append('nomic-ai/nomic-embed-text-v1.5')

    rer = os.getenv('RERANKER_MODEL')
    if rer:
        models.append(rer)
    else:
        models.append('cross-encoder/ms-marco-MiniLM-L-6-v2')

    extra = os.getenv('PREBUNDLED_MODELS', '')
    if extra:
        models += [m.strip() for m in extra.split(',') if m.strip()]

    # De-duplicate while preserving order
    seen = set()
    out: List[str] = []
    for m in models:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def ensure_models_available(models: List[str], fail_on_missing: bool = True) -> Dict[str, str]:
    """Ensure each model in `models` is present in the local HF snapshot cache.

    Args:
        models: list of HF repo ids (e.g., 'nomic-ai/nomic-embed-text-v1.5')
        fail_on_missing: if True raise RuntimeError when a model is not locally present

    Returns:
        Mapping of model id -> local path returned by snapshot_download.

    Raises:
        RuntimeError when a required model is missing (and fail_on_missing=True)
    """
    if snapshot_download is None:
        msg = 'huggingface_hub.snapshot_download not available; cannot verify local models'
        logger.error(msg)
        if fail_on_missing:
            raise RuntimeError(msg)
        return {}

    # Force fully offline — never reach out to HuggingFace.
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

    results: Dict[str, str] = {}
    for repo_id in models:
        try:
            logger.info('Checking local snapshot for model: %s', repo_id)
            local_path = snapshot_download(repo_id=repo_id, local_files_only=True)
            results[repo_id] = local_path
            logger.info('Local model present: %s -> %s', repo_id, local_path)
        except Exception as e:  # pragma: no cover - let callers handle failure
            logger.error('Model %s not available locally: %s', repo_id, e)
            if fail_on_missing:
                raise RuntimeError(f'Model {repo_id} not available locally: {e}') from e
    return results


__all__ = ['get_default_models_to_prewarm', 'ensure_models_available']