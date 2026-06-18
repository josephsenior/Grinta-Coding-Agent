"""Split submodule — see package facade for public API."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.context.canonical_state import (
    apply_canonical_patch,
    load_canonical_state,
    reduce_events_into_state,
    render_canonical_state_for_prompt,
    save_canonical_state,
    validate_canonical_state_for_compaction,
)
from backend.context.compaction.compact_boundary import project_after_compact_boundary
from backend.context.compaction.compaction_finalizer import finalize_compaction_artifacts
from backend.context.compactor.compactor import Compaction
from backend.context.compaction.condensed_history import CondensedHistory
from backend.context.context_budget import ContextBudget, record_post_compact_baseline
from backend.context.prompt.context_packet import (
    CONTEXT_PACKET_MARKER,
    build_context_packet_observation,
)
from backend.context.continuity_eval import compaction_passes_continuity_gate
from backend.context.compaction.microcompact import apply_microcompact
from backend.context.compaction.pre_condensation_snapshot import (
    delete_staging_snapshot,
    extract_snapshot,
    save_snapshot,
)
from backend.context.prompt.prompt_window import select_prompt_events
from backend.context.memory.session_context import bind_session_context
from backend.context.memory.session_memory import (
    build_compaction_summary,
    maybe_update,
    session_memory_exists,
)
from backend.context.tool_result_storage import (
    apply_frozen_tool_replacements,
    apply_tool_result_budget,
)
from backend.core.constants import (
    DEFAULT_BOUNDARY_COMPACT_COOLDOWN_SECONDS,
    DEFAULT_COMPACT_MIN_PRUNED_EVENTS,
    DEFAULT_COMPACT_MIN_TOKEN_REDUCTION,
    DEFAULT_DEGRADED_COMPACT_TAIL_RATIO,
    DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS,
    DEFAULT_INEFFECTIVE_COMPACT_BACKOFF_SECONDS,
    DEFAULT_INEFFECTIVE_COMPACT_MAX_SKIP_EVENTS,
    DEFAULT_INEFFECTIVE_COMPACT_SKIP_EVENTS,
    DEFAULT_LLM_COMPACT_COOLDOWN_SECONDS,
    DEFAULT_MICROCOMPACT_PRESERVE_RECENT,
    DEFAULT_PROMPT_MIN_TAIL_TOKENS,
    DEFAULT_PROMPT_MIN_TOOL_LOOPS,
)
from backend.core.logger import app_logger as logger
from backend.inference.capabilities.context_limits import limits_from_config
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import Event

if TYPE_CHECKING:
    from backend.core.config.compactor_config import ContextPipelineConfig
    from backend.inference.llm_registry import LLMRegistry
    from backend.orchestration.state.state import State


_LAST_LLM_COMPACT_KEY = 'last_llm_compact_attempt'
_LAST_BOUNDARY_COMPACT_KEY = 'last_boundary_compact_at'
_JUST_COMPACTED_KEY = 'just_compacted'
_SKIP_COMPACTION_UNTIL_KEY = 'skip_compaction_until_event_id'
_INEFFECTIVE_COMPACT_STREAK_KEY = 'ineffective_compact_streak'
_INEFFECTIVE_COMPACT_UNTIL_KEY = 'ineffective_compact_until'
_CONSECUTIVE_CONDENSATION_KEY = 'consecutive_condensation_steps'
_CONTINUITY_REJECTION_FP_KEY = 'last_continuity_rejection_fingerprint'
_CONTINUITY_REJECTION_STREAK_KEY = 'continuity_rejection_streak'
_DETERMINISTIC_FALLBACK_THRESHOLD = 2
_COMPACTION_TARGET_RATIO = 0.7


@dataclass
class PipelineStepResult:
    """Processed events for prompt build plus optional pending condensation."""

    events: list[Event]
    pending_action: CondensationAction | None = None
    compacted: bool = False


@dataclass(frozen=True)
class _ContinuityGateDecision:
    passed: bool
    canonical_ok: bool
    fingerprint: str
    missing: tuple[str, ...]
    score: float
    matched: int
    total: int


