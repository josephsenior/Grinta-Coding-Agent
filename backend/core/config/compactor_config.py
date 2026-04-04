"""Configuration structures for conversation compactor behaviour."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend._canonical import CanonicalModelMetaclass
from backend.core import logger
from backend.core.constants import (
    DEFAULT_BROWSER_COMPACTOR_ATTENTION_WINDOW,
    DEFAULT_COMPACTOR_ATTENTION_WINDOW,
    DEFAULT_COMPACTOR_KEEP_FIRST,
    DEFAULT_COMPACTOR_MAX_EVENT_LENGTH,
    DEFAULT_COMPACTOR_MAX_EVENTS,
    DEFAULT_COMPACTOR_MAX_SIZE,
    DEFAULT_SMART_COMPACTOR_IMPORTANCE_THRESHOLD,
    DEFAULT_SMART_COMPACTOR_KEEP_FIRST,
    DEFAULT_SMART_COMPACTOR_MAX_SIZE,
    DEFAULT_SMART_COMPACTOR_RECENCY_BONUS_WINDOW,
)

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


class BrowserOutputCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for the BrowserOutputCompactor."""

    type: Literal['browser_output_masking'] = Field(default='browser_output_masking')
    attention_window: int = Field(
        default=DEFAULT_BROWSER_COMPACTOR_ATTENTION_WINDOW,
        description='The number of most recent browser output observations that will not be masked.',
        ge=1,
    )


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


class LLMSummarizingCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for LLMSummarizingCompactor."""

    type: Literal['llm'] = Field(default='llm')
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
            'Optional token budget. When set, condensation also triggers if '
            'the estimated token count of the view exceeds this limit.'
        ),
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


class LLMAttentionCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for LLMAttentionCompactor."""

    type: Literal['llm_attention'] = Field(default='llm_attention')
    llm_config: LLMConfig = Field(
        ..., description='Configuration for the LLM to use for attention.'
    )
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
    model_config = ConfigDict(extra='forbid')


class CompactorPipelineConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for the CompactorPipeline."""

    type: Literal['pipeline'] = Field(default='pipeline')
    compactors: list[CompactorConfig] = Field(
        default_factory=list,
        description='List of compactor configurations to be used in the pipeline.',
    )
    model_config = ConfigDict(extra='forbid')


class ConversationWindowCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for ConversationWindowCompactor.

    Not currently supported by the TOML or ENV_VAR configuration strategies.
    """

    type: Literal['conversation_window'] = Field(default='conversation_window')
    max_events: int = Field(
        default=100,
        description=(
            'Proactive condensation threshold. When the event count exceeds '
            'this value the compactor trims history BEFORE hitting the '
            'context window limit.'
        ),
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


class SemanticCompactorConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for SemanticCompactor."""

    type: Literal['semantic'] = Field(default='semantic')
    llm_config: LLMConfig | str | None = Field(
        default=None, description='LLM config name to use for summarization (optional).'
    )
    max_size: int = Field(default=DEFAULT_SMART_COMPACTOR_MAX_SIZE, ge=2)
    keep_first: int = Field(default=DEFAULT_SMART_COMPACTOR_KEEP_FIRST, ge=0)
    similarity_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    model_name: str = Field(default='all-MiniLM-L6-v2')
    token_budget: int | None = Field(default=None, ge=1)

    model_config = ConfigDict(extra='forbid')


# Define the union type for all compactor configurations
CompactorConfig = (
    NoOpCompactorConfig
    | ObservationMaskingCompactorConfig
    | BrowserOutputCompactorConfig
    | RecentEventsCompactorConfig
    | LLMSummarizingCompactorConfig
    | AmortizedPruningCompactorConfig
    | LLMAttentionCompactorConfig
    | StructuredSummaryCompactorConfig
    | CompactorPipelineConfig
    | ConversationWindowCompactorConfig
    | SmartCompactorConfig
    | AutoCompactorConfig
    | SemanticCompactorConfig
)


def compactor_config_from_toml_section(
    data: dict, llm_configs: dict | None = None
) -> dict[str, CompactorConfig]:
    """Create a CompactorConfig instance from a TOML dictionary representing the [compactor] section.

    For CompactorConfig, the handling is different since it's a union type. The type of compactor
    is determined by the 'type' field in the section.

    Example:
    Parse compactor config like:
        [compactor]
        type = "noop"

    For compactors that require an LLM config, you can specify the name of an LLM config:
        [compactor]
        type = "llm"
        llm_config = "my_llm"  # References [llm.my_llm] section

    Args:
        data: The TOML dictionary representing the [compactor] section.
        llm_configs: Optional dictionary of LLMConfig objects keyed by name.

    Returns:
        dict[str, CompactorConfig]: A mapping where the key "compactor" corresponds to the configuration.

    """
    compactor_mapping: dict[str, CompactorConfig] = {}
    try:
        compactor_type = data.get('type', 'smart')
        if (
            compactor_type in ('llm', 'llm_attention', 'smart')
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
        'recent': RecentEventsCompactorConfig,
        'llm': LLMSummarizingCompactorConfig,
        'amortized': AmortizedPruningCompactorConfig,
        'llm_attention': LLMAttentionCompactorConfig,
        'structured': StructuredSummaryCompactorConfig,
        'pipeline': CompactorPipelineConfig,
        'conversation_window': ConversationWindowCompactorConfig,
        'browser_output_masking': BrowserOutputCompactorConfig,
        'smart': SmartCompactorConfig,
        'auto': AutoCompactorConfig,
        'semantic': SemanticCompactorConfig,
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
LLMSummarizingCompactorConfig.model_rebuild()
LLMAttentionCompactorConfig.model_rebuild()
StructuredSummaryCompactorConfig.model_rebuild()
CompactorPipelineConfig.model_rebuild()
SmartCompactorConfig.model_rebuild()
AutoCompactorConfig.model_rebuild()
SemanticCompactorConfig.model_rebuild()
