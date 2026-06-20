"""Compaction and compactor strategies for long conversation histories."""

# Import implementations to trigger compactor registrations.
from backend.context.compactor import strategies  # noqa: F401
from backend.context.compactor.compact_boundary import (  # noqa: F401
    CompactBoundaryInfo,
    find_last_condensation_action,
    project_after_compact_boundary,
)
from backend.context.compactor.compaction_finalizer import (  # noqa: F401
    finalize_compaction_artifacts,
)
from backend.context.compactor.compactor import (
    COMPACTOR_REGISTRY,
    BaseLLMCompactor,
    Compaction,
    Compactor,
    RollingCompactor,
    get_compaction_metadata,
)
from backend.context.compactor.condensed_history import CondensedHistory  # noqa: F401
from backend.context.compactor.microcompact import apply_microcompact  # noqa: F401
from backend.context.compactor.pre_condensation_snapshot import (  # noqa: F401
    commit_snapshot,
    delete_snapshot,
    delete_staging_snapshot,
    extract_snapshot,
    load_snapshot,
    save_snapshot,
)
from backend.context.view import View

__all__ = [
    'BaseLLMCompactor',
    'COMPACTOR_REGISTRY',
    'Compaction',
    'Compactor',
    'CompactBoundaryInfo',
    'CondensedHistory',
    'RollingCompactor',
    'apply_microcompact',
    'commit_snapshot',
    'delete_snapshot',
    'delete_staging_snapshot',
    'extract_snapshot',
    'finalize_compaction_artifacts',
    'find_last_condensation_action',
    'get_compaction_metadata',
    'load_snapshot',
    'project_after_compact_boundary',
    'save_snapshot',
    'View',
]
