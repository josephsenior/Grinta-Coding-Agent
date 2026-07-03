"""Configuration structures for conversation compactor behaviour."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend._canonical import CanonicalModelMetaclass
from backend.core.constants import (
    DEFAULT_COMPACTOR_ATTENTION_WINDOW,
    DEFAULT_COMPACTOR_KEEP_FIRST,
    DEFAULT_COMPACTOR_MAX_EVENT_LENGTH,
    DEFAULT_COMPACTOR_MAX_EVENTS,
    DEFAULT_COMPACTOR_MAX_SIZE,
    DEFAULT_MICROCOMPACT_PRESERVE_RECENT,
    DEFAULT_SMART_COMPACTOR_IMPORTANCE_THRESHOLD,
    DEFAULT_SMART_COMPACTOR_KEEP_FIRST,
    DEFAULT_SMART_COMPACTOR_MAX_SIZE,
    DEFAULT_SMART_COMPACTOR_RECENCY_BONUS_WINDOW,
)
from backend.core.logging import logger

if TYPE_CHECKING:
    from backend.core.config.llm_config import LLMConfig
else:
    LLMConfig = Any  # For runtime when TYPE_CHECKING is False


class NoOpCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for NoOpCompactor."""

    type: Literal['noop'] = Field(default='noop')
    model_config = ConfigDict(extra='forbid')


class ObservationMaskingCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for ObservationMaskingCompactor."""

    type: Literal['observation_masking'] = Field(default='observation_masking')
    attention_window: int = Field(
        default=DEFAULT_COMPACTOR_ATTENTION_WINDOW,
        description='The number of most-recent events where observations will not be masked.',
        ge=1,
    )
    model_config = ConfigDict(extra='forbid')


class MicrocompactCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for MicrocompactCompactor."""

    type: Literal['microcompact'] = Field(default='microcompact')
    preserve_recent: int = Field(
        default=DEFAULT_MICROCOMPACT_PRESERVE_RECENT,
        description=(
            'Number of most-recent events whose tool observation bodies stay intact.'
        ),
        ge=1,
    )
    model_config = ConfigDict(extra='forbid')


class RecentEventsCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for RecentEventsCompactor."""

    type: Literal['recent'] = Field(default='recent')
    keep_first: int = Field(
        default=DEFAULT_COMPACTOR_KEEP_FIRST,
        description='The number of initial events to condense.',
        ge=0,
    )
    max_events: int = Field(
        default=DEFAULT_COMPACTOR_MAX_EVENTS,
        description='Maximum number of events to keep.',
        ge=1,
    )
    model_config = ConfigDict(extra='forbid')


class AmortizedPruningCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for AmortizedPruningCompactor."""

    type: Literal['amortized'] = Field(default='amortized')
    max_size: int = Field(
        default=DEFAULT_COMPACTOR_MAX_SIZE,
        description='Maximum size of the condensed history before triggering pruning.',
        ge=2,
    )
    keep_first: int = Field(
        default=DEFAULT_COMPACTOR_KEEP_FIRST,
        description='Number of initial events to always keep in history.',
        ge=0,
    )
    token_budget: int | None = Field(
        default=None,
        description=(
            'Optional token budget.  When set, condensation also triggers if '
            'the estimated token count of the view exceeds this limit.'
        ),
        ge=1,
    )
    model_config = ConfigDict(extra='forbid')


class StructuredSummaryCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for StructuredSummaryCompactor instances."""

    type: Literal['structured'] = Field(default='structured')
    llm_config: LLMConfig = Field(
        ..., description='Configuration for the LLM to use for condensing.'
    )
    keep_first: int = Field(
        default=DEFAULT_COMPACTOR_KEEP_FIRST,
        description='Number of initial events to always keep in history.',
        ge=0,
    )
    max_size: int = Field(
        default=DEFAULT_COMPACTOR_MAX_SIZE,
        description='Maximum size of the condensed history before triggering pruning.',
        ge=2,
    )
    max_event_length: int = Field(
        default=DEFAULT_COMPACTOR_MAX_EVENT_LENGTH,
        description='Maximum length of the event representations to be passed to the LLM.',
    )
    token_budget: int | None = Field(
        default=None,
        description=(
            'Optional token budget.  When set, condensation also triggers if '
            'the estimated token count of the view exceeds this limit.'
        ),
        ge=1,
    )
    min_prose_length: int = Field(
        default=2000,
        description=(
            'Minimum character length for an accepted prose summary. Shorter '
            'outputs are treated as degraded so the pipeline falls back to '
            'deterministic compaction instead of wiping history.'
        ),
        ge=1,
    )
    max_repair_attempts: int = Field(
        default=2,
        description=(
            'Same-prompt retries when the prose sanity gate fails. 0 means a '
            'short/empty output immediately degrades to the deterministic fallback.'
        ),
        ge=0,
    )
    model_config = ConfigDict(extra='forbid')


class CompactorPipelineConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for the CompactorPipeline."""

    type: Literal['pipeline'] = Field(default='pipeline')
    compactors: list[CompactorConfig] = Field(
        default_factory=list,
        description='List of compactor configurations to be used in the pipeline.',
    )
    model_config = ConfigDict(extra='forbid')


class ContextPipelineConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for the unified ContextPipeline compaction architecture."""

    type: Literal['context_pipeline'] = Field(default='context_pipeline')
    llm_config: LLMConfig | str | None = Field(
        default=None,
        description='LLM config for Layer 5b structured compaction.',
    )
    allow_llm_hot_path: bool = Field(
        default=True,
        description='Allow LLM structured compaction on the hot path.',
    )
    preserve_recent: int = Field(
        default=DEFAULT_MICROCOMPACT_PRESERVE_RECENT,
        description='Microcompact preservation window (Layer 3).',
        ge=1,
    )
    model_config = ConfigDict(extra='forbid')


class AutoCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for task-aware automatic compactor selection.

    When ``type = "auto"`` the system analyses the current event stream
    and picks the most appropriate compactor strategy dynamically.
    """

    type: Literal['auto'] = Field(default='auto')
    llm_config: LLMConfig | str | None = Field(
        default=None,
        description='LLM config name made available to LLM-based strategies when auto-selected.',
    )
    allow_llm_hot_path: bool = Field(
        default=True,
        description=(
            'Allow normal-turn auto compaction to use LLM-backed strategies. '
            'Enabled by default for coding sessions so long runs get semantic '
            'summaries instead of deterministic-only pruning; explicit condensation '
            'may still use LLM summaries when this is disabled.'
        ),
    )
    model_config = ConfigDict(extra='forbid')


class CompositionCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for CompositionCompactor with layered pipeline."""

    type: Literal['composition'] = Field(default='composition')
    microcompact_recency: int = Field(
        default=50,
        description='Number of most-recent events to keep raw during microcompact.',
        ge=1,
    )
    snip_max_events: int = Field(
        default=1000,
        description='Hard cap on total event count.',
        ge=100,
    )
    reactive_max_events: int | None = Field(
        default=None,
        description=(
            'Secondary event cap for the reactive safety-net layer. When the '
            'pipeline still exceeds this after snip/summary/reattach, reactive '
            'drops the oldest half. Defaults to snip_max_events * 0.5.'
        ),
        ge=1,
    )
    summary_recency: int = Field(
        default=50,
        description='Number of most-recent events to exclude from summarization.',
        ge=0,
    )
    post_compact_budget: int = Field(
        default=50000,
        description='Token budget for re-attaching files after compaction.',
        ge=0,
    )
    post_compact_max_files: int = Field(
        default=5,
        description='Maximum number of files to re-attach.',
        ge=0,
    )
    llm_config: LLMConfig | str | None = Field(
        default=None,
        description='LLM config for the summary layer. When set, old events before the recency window are summarized via LLM.',
    )
    model_config = ConfigDict(extra='forbid')


class SmartCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for SmartCompactor with LLM-assisted importance scoring."""

    type: Literal['smart'] = Field(default='smart')
    llm_config: LLMConfig | str | None = Field(
        default=None, description='LLM config name to use for importance scoring.'
    )
    max_size: int = Field(
        default=DEFAULT_SMART_COMPACTOR_MAX_SIZE,
        description='Maximum events before triggering condensation.',
        ge=2,
    )
    keep_first: int = Field(
        default=DEFAULT_SMART_COMPACTOR_KEEP_FIRST,
        description='Number of initial events to always keep.',
        ge=0,
    )
    importance_threshold: float = Field(
        default=DEFAULT_SMART_COMPACTOR_IMPORTANCE_THRESHOLD,
        description='Minimum importance score to keep event (0.0-1.0).',
        ge=0.0,
        le=1.0,
    )
    recency_bonus_window: int = Field(
        default=DEFAULT_SMART_COMPACTOR_RECENCY_BONUS_WINDOW,
        description='Number of recent events to give recency bonus.',
        ge=1,
    )
    token_budget: int | None = Field(
        default=None,
        description=(
            'Optional token budget.  When set, condensation also triggers if '
            'the estimated token count of the view exceeds this limit.'
        ),
        ge=1,
    )
    model_config = ConfigDict(extra='forbid')


# Define the union type for all compactor configurations
CompactorConfig = (
    NoOpCompactorConfig
    | ObservationMaskingCompactorConfig
    | MicrocompactCompactorConfig
    | RecentEventsCompactorConfig
    | AmortizedPruningCompactorConfig
    | StructuredSummaryCompactorConfig
    | CompactorPipelineConfig
    | CompositionCompactorConfig
    | SmartCompactorConfig
    | AutoCompactorConfig
    | ContextPipelineConfig
)


def compactor_config_from_toml_section(
    data: dict, llm_configs: dict | None = None
) -> dict[str, CompactorConfig]:
    """Create a CompactorConfig instance from a compactor settings dictionary.

    For CompactorConfig, the handling is different since it's a union type. The type of compactor
    is determined by the 'type' field in the section.

    Example:
        {"type": "noop"}

    For compactors that require an LLM config, you can specify the key of an LLM config:
        {"type": "smart", "llm_config": "my_llm"}

    Args:
        data: Compactor settings dictionary.
        llm_configs: Optional dictionary of LLMConfig objects keyed by name.

    Returns:
        dict[str, CompactorConfig]: A mapping where the key "compactor" corresponds to the configuration.

    """
    compactor_mapping: dict[str, CompactorConfig] = {}
    try:
        compactor_type = data.get('type', 'context_pipeline')
        if (
            compactor_type in ('smart', 'structured')
            and 'llm_config' in data
            and isinstance(data['llm_config'], str)
        ):
            llm_config_name = data['llm_config']
            if llm_configs and llm_config_name in llm_configs:
                data_copy = data.copy()
                data_copy['llm_config'] = llm_configs[llm_config_name]
                config = create_compactor_config(compactor_type, data_copy)
            else:
                logger.app_logger.warning(
                    "LLM config '%s' not found for compactor type '%s'. Falling back to NoOpCompactor for safety.",
                    llm_config_name,
                    compactor_type,
                )
                config = NoOpCompactorConfig(type='noop')
        else:
            config = create_compactor_config(compactor_type, data)
        compactor_mapping['compactor'] = config
    except (ValidationError, ValueError) as e:
        logger.app_logger.warning(
            'Invalid compactor configuration: %s. Using NoOpCompactorConfig.', e
        )
        config = NoOpCompactorConfig(type='noop')
        compactor_mapping['compactor'] = config
    return compactor_mapping


def create_compactor_config(compactor_type: str, data: dict) -> CompactorConfig:
    """Create a CompactorConfig instance based on the specified type.

    Args:
        compactor_type: The type of compactor to create.
        data: The configuration data.

    Returns:
        A CompactorConfig instance.

    Raises:
        ValueError: If the compactor type is unknown.
        ValidationError: If the provided data fails validation for the compactor type.

    """
    compactor_classes = {
        'noop': NoOpCompactorConfig,
        'observation_masking': ObservationMaskingCompactorConfig,
        'microcompact': MicrocompactCompactorConfig,
        'recent': RecentEventsCompactorConfig,
        'amortized': AmortizedPruningCompactorConfig,
        'structured': StructuredSummaryCompactorConfig,
        'composition': CompositionCompactorConfig,
        'pipeline': CompactorPipelineConfig,
        'smart': SmartCompactorConfig,
        'auto': AutoCompactorConfig,
        'context_pipeline': ContextPipelineConfig,
    }
    if compactor_type not in compactor_classes:
        msg = f'Unknown compactor type: {compactor_type}'
        raise ValueError(msg)
    try:
        config_class = compactor_classes[compactor_type]
        return cast('CompactorConfig', config_class(**data))
    except ValidationError as e:
        msg = f"Validation failed for compactor type '{compactor_type}': {e}"
        raise ValueError(msg) from e


# Rebuild models that have LLMConfig forward references
StructuredSummaryCompactorConfig.model_rebuild()
CompactorPipelineConfig.model_rebuild()
SmartCompactorConfig.model_rebuild()
AutoCompactorConfig.model_rebuild()
ContextPipelineConfig.model_rebuild()
