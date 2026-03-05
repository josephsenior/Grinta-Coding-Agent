"""Configuration structures for conversation condenser behaviour."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend._canonical import CanonicalModelMetaclass
from backend.core import logger
from backend.core.constants import (
    DEFAULT_BROWSER_CONDENSER_ATTENTION_WINDOW,
    DEFAULT_CONDENSER_ATTENTION_WINDOW,
    DEFAULT_CONDENSER_KEEP_FIRST,
    DEFAULT_CONDENSER_MAX_EVENT_LENGTH,
    DEFAULT_CONDENSER_MAX_EVENTS,
    DEFAULT_CONDENSER_MAX_SIZE,
    DEFAULT_SMART_CONDENSER_IMPORTANCE_THRESHOLD,
    DEFAULT_SMART_CONDENSER_KEEP_FIRST,
    DEFAULT_SMART_CONDENSER_MAX_SIZE,
    DEFAULT_SMART_CONDENSER_RECENCY_BONUS_WINDOW,
)

if TYPE_CHECKING:
    from backend.core.config.llm_config import LLMConfig
else:
    LLMConfig = Any  # For runtime when TYPE_CHECKING is False


class NoOpCondenserConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for NoOpCondenser."""

    type: Literal["noop"] = Field(default="noop")
    model_config = ConfigDict(extra="forbid")


class ObservationMaskingCondenserConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for ObservationMaskingCondenser."""

    type: Literal["observation_masking"] = Field(default="observation_masking")
    attention_window: int = Field(
        default=DEFAULT_CONDENSER_ATTENTION_WINDOW,
        description="The number of most-recent events where observations will not be masked.",
        ge=1,
    )
    model_config = ConfigDict(extra="forbid")


class BrowserOutputCondenserConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for the BrowserOutputCondenser."""

    type: Literal["browser_output_masking"] = Field(default="browser_output_masking")
    attention_window: int = Field(
        default=DEFAULT_BROWSER_CONDENSER_ATTENTION_WINDOW,
        description="The number of most recent browser output observations that will not be masked.",
        ge=1,
    )


class RecentEventsCondenserConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for RecentEventsCondenser."""

    type: Literal["recent"] = Field(default="recent")
    keep_first: int = Field(
        default=DEFAULT_CONDENSER_KEEP_FIRST,
        description="The number of initial events to condense.",
        ge=0,
    )
    max_events: int = Field(
        default=DEFAULT_CONDENSER_MAX_EVENTS,
        description="Maximum number of events to keep.",
        ge=1,
    )
    model_config = ConfigDict(extra="forbid")


class LLMSummarizingCondenserConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for LLMCondenser."""

    type: Literal["llm"] = Field(default="llm")
    llm_config: LLMConfig = Field(
        ..., description="Configuration for the LLM to use for condensing."
    )
    keep_first: int = Field(
        default=DEFAULT_CONDENSER_KEEP_FIRST,
        description="Number of initial events to always keep in history.",
        ge=0,
    )
    max_size: int = Field(
        default=DEFAULT_CONDENSER_MAX_SIZE,
        description="Maximum size of the condensed history before triggering forgetting.",
        ge=2,
    )
    max_event_length: int = Field(
        default=DEFAULT_CONDENSER_MAX_EVENT_LENGTH,
        description="Maximum length of the event representations to be passed to the LLM.",
    )
    token_budget: int | None = Field(
        default=None,
        description=(
            "Optional token budget. When set, condensation also triggers if "
            "the estimated token count of the view exceeds this limit."
        ),
        ge=1,
    )
    model_config = ConfigDict(extra="forbid")


class AmortizedForgettingCondenserConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for AmortizedForgettingCondenser."""

    type: Literal["amortized"] = Field(default="amortized")
    max_size: int = Field(
        default=DEFAULT_CONDENSER_MAX_SIZE,
        description="Maximum size of the condensed history before triggering forgetting.",
        ge=2,
    )
    keep_first: int = Field(
        default=DEFAULT_CONDENSER_KEEP_FIRST,
        description="Number of initial events to always keep in history.",
        ge=0,
    )
    token_budget: int | None = Field(
        default=None,
        description=(
            "Optional token budget.  When set, condensation also triggers if "
            "the estimated token count of the view exceeds this limit."
        ),
        ge=1,
    )
    model_config = ConfigDict(extra="forbid")


class LLMAttentionCondenserConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for LLMAttentionCondenser."""

    type: Literal["llm_attention"] = Field(default="llm_attention")
    llm_config: LLMConfig = Field(
        ..., description="Configuration for the LLM to use for attention."
    )
    max_size: int = Field(
        default=DEFAULT_CONDENSER_MAX_SIZE,
        description="Maximum size of the condensed history before triggering forgetting.",
        ge=2,
    )
    keep_first: int = Field(
        default=DEFAULT_CONDENSER_KEEP_FIRST,
        description="Number of initial events to always keep in history.",
        ge=0,
    )
    token_budget: int | None = Field(
        default=None,
        description=(
            "Optional token budget.  When set, condensation also triggers if "
            "the estimated token count of the view exceeds this limit."
        ),
        ge=1,
    )
    model_config = ConfigDict(extra="forbid")


class StructuredSummaryCondenserConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for StructuredSummaryCondenser instances."""

    type: Literal["structured"] = Field(default="structured")
    llm_config: LLMConfig = Field(
        ..., description="Configuration for the LLM to use for condensing."
    )
    keep_first: int = Field(
        default=DEFAULT_CONDENSER_KEEP_FIRST,
        description="Number of initial events to always keep in history.",
        ge=0,
    )
    max_size: int = Field(
        default=DEFAULT_CONDENSER_MAX_SIZE,
        description="Maximum size of the condensed history before triggering forgetting.",
        ge=2,
    )
    max_event_length: int = Field(
        default=DEFAULT_CONDENSER_MAX_EVENT_LENGTH,
        description="Maximum length of the event representations to be passed to the LLM.",
    )
    token_budget: int | None = Field(
        default=None,
        description=(
            "Optional token budget.  When set, condensation also triggers if "
            "the estimated token count of the view exceeds this limit."
        ),
        ge=1,
    )
    model_config = ConfigDict(extra="forbid")


class CondenserPipelineConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for the CondenserPipeline."""

    type: Literal["pipeline"] = Field(default="pipeline")
    condensers: list[CondenserConfig] = Field(
        default_factory=list,
        description="List of condenser configurations to be used in the pipeline.",
    )
    model_config = ConfigDict(extra="forbid")


class ConversationWindowCondenserConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for ConversationWindowCondenser.

    Not currently supported by the TOML or ENV_VAR configuration strategies.
    """

    type: Literal["conversation_window"] = Field(default="conversation_window")
    model_config = ConfigDict(extra="forbid")


class AutoCondenserConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for task-aware automatic condenser selection.

    When ``type = "auto"`` the system analyses the current event stream
    and picks the most appropriate condenser strategy dynamically.
    """

    type: Literal["auto"] = Field(default="auto")
    llm_config: LLMConfig | str | None = Field(
        default=None,
        description="LLM config name made available to LLM-based strategies when auto-selected.",
    )
    model_config = ConfigDict(extra="forbid")


class SmartCondenserConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for SmartCondenser with LLM-assisted importance scoring."""

    type: Literal["smart"] = Field(default="smart")
    llm_config: LLMConfig | str | None = Field(
        default=None, description="LLM config name to use for importance scoring."
    )
    max_size: int = Field(
        default=DEFAULT_SMART_CONDENSER_MAX_SIZE,
        description="Maximum events before triggering condensation.",
        ge=2,
    )
    keep_first: int = Field(
        default=DEFAULT_SMART_CONDENSER_KEEP_FIRST,
        description="Number of initial events to always keep.",
        ge=0,
    )
    importance_threshold: float = Field(
        default=DEFAULT_SMART_CONDENSER_IMPORTANCE_THRESHOLD,
        description="Minimum importance score to keep event (0.0-1.0).",
        ge=0.0,
        le=1.0,
    )
    recency_bonus_window: int = Field(
        default=DEFAULT_SMART_CONDENSER_RECENCY_BONUS_WINDOW,
        description="Number of recent events to give recency bonus.",
        ge=1,
    )
    token_budget: int | None = Field(
        default=None,
        description=(
            "Optional token budget.  When set, condensation also triggers if "
            "the estimated token count of the view exceeds this limit."
        ),
        ge=1,
    )
    model_config = ConfigDict(extra="forbid")


class SemanticCondenserConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for SemanticCondenser."""

    type: Literal["semantic"] = Field(default="semantic")
    llm_config: LLMConfig | str | None = Field(
        default=None, description="LLM config name to use for summarization (optional)."
    )
    max_size: int = Field(default=DEFAULT_SMART_CONDENSER_MAX_SIZE, ge=2)
    keep_first: int = Field(default=DEFAULT_SMART_CONDENSER_KEEP_FIRST, ge=0)
    similarity_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    model_name: str = Field(default="all-MiniLM-L6-v2")
    token_budget: int | None = Field(default=None, ge=1)

    model_config = ConfigDict(extra="forbid")


# Define the union type for all condenser configurations
CondenserConfig = (
    NoOpCondenserConfig
    | ObservationMaskingCondenserConfig
    | BrowserOutputCondenserConfig
    | RecentEventsCondenserConfig
    | LLMSummarizingCondenserConfig
    | AmortizedForgettingCondenserConfig
    | LLMAttentionCondenserConfig
    | StructuredSummaryCondenserConfig
    | CondenserPipelineConfig
    | ConversationWindowCondenserConfig
    | SmartCondenserConfig
    | AutoCondenserConfig
    | SemanticCondenserConfig
)


def condenser_config_from_toml_section(
    data: dict, llm_configs: dict | None = None
) -> dict[str, CondenserConfig]:
    """Create a CondenserConfig instance from a toml dictionary representing the [condenser] section.

    For CondenserConfig, the handling is different since it's a union type. The type of condenser
    is determined by the 'type' field in the section.

    Example:
    Parse condenser config like:
        [condenser]
        type = "noop"

    For condensers that require an LLM config, you can specify the name of an LLM config:
        [condenser]
        type = "llm"
        llm_config = "my_llm"  # References [llm.my_llm] section

    Args:
        data: The TOML dictionary representing the [condenser] section.
        llm_configs: Optional dictionary of LLMConfig objects keyed by name.

    Returns:
        dict[str, CondenserConfig]: A mapping where the key "condenser" corresponds to the configuration.

    """
    condenser_mapping: dict[str, CondenserConfig] = {}
    try:
        condenser_type = data.get("type", "smart")
        if (
            condenser_type in ("llm", "llm_attention", "smart")
            and "llm_config" in data
            and isinstance(data["llm_config"], str)
        ):
            llm_config_name = data["llm_config"]
            if llm_configs and llm_config_name in llm_configs:
                data_copy = data.copy()
                data_copy["llm_config"] = llm_configs[llm_config_name]
                config = create_condenser_config(condenser_type, data_copy)
            else:
                # IMPROVED BEHAVIOR: If LLM config reference is missing, fall back to NoOpCondenser
                # This prevents creating LLM-based condensers with None config which could fail silently
                logger.forge_logger.warning(
                    "LLM config '%s' not found for condenser type '%s'. Falling back to NoOpCondenser for safety.",
                    llm_config_name,
                    condenser_type,
                )
                config = NoOpCondenserConfig(type="noop")
        else:
            config = create_condenser_config(condenser_type, data)
        condenser_mapping["condenser"] = config
    except (ValidationError, ValueError) as e:
        logger.forge_logger.warning(
            "Invalid condenser configuration: %s. Using NoOpCondenserConfig.", e
        )
        config = NoOpCondenserConfig(type="noop")
        condenser_mapping["condenser"] = config
    return condenser_mapping


def create_condenser_config(condenser_type: str, data: dict) -> CondenserConfig:
    """Create a CondenserConfig instance based on the specified type.

    Args:
        condenser_type: The type of condenser to create.
        data: The configuration data.

    Returns:
        A CondenserConfig instance.

    Raises:
        ValueError: If the condenser type is unknown.
        ValidationError: If the provided data fails validation for the condenser type.

    """
    condenser_classes = {
        "noop": NoOpCondenserConfig,
        "observation_masking": ObservationMaskingCondenserConfig,
        "recent": RecentEventsCondenserConfig,
        "llm": LLMSummarizingCondenserConfig,
        "amortized": AmortizedForgettingCondenserConfig,
        "llm_attention": LLMAttentionCondenserConfig,
        "structured": StructuredSummaryCondenserConfig,
        "pipeline": CondenserPipelineConfig,
        "conversation_window": ConversationWindowCondenserConfig,
        "browser_output_masking": BrowserOutputCondenserConfig,
        "smart": SmartCondenserConfig,
        "auto": AutoCondenserConfig,
        "semantic": SemanticCondenserConfig,
    }
    if condenser_type not in condenser_classes:
        msg = f"Unknown condenser type: {condenser_type}"
        raise ValueError(msg)
    try:
        config_class = condenser_classes[condenser_type]
        return cast("CondenserConfig", config_class(**data))
    except ValidationError as e:
        msg = f"Validation failed for condenser type '{condenser_type}': {e}"
        raise ValueError(msg) from e


# Rebuild models that have LLMConfig forward references
LLMSummarizingCondenserConfig.model_rebuild()
LLMAttentionCondenserConfig.model_rebuild()
StructuredSummaryCondenserConfig.model_rebuild()
CondenserPipelineConfig.model_rebuild()
SmartCondenserConfig.model_rebuild()
AutoCondenserConfig.model_rebuild()
SemanticCondenserConfig.model_rebuild()
