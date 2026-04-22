"""Configuration models describing agent-specific settings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from backend._canonical import CanonicalModelMetaclass

# Import CompactorConfig directly - needed for Pydantic validation
from backend.core.config.compactor_config import AutoCompactorConfig, CompactorConfig
from backend.core.config.config_telemetry import config_telemetry
from backend.core.constants import (
    CURRENT_AGENT_CONFIG_SCHEMA_VERSION,
    DEFAULT_AGENT_AUTO_LINT_ENABLED,
    DEFAULT_AGENT_AUTO_PLANNING_ENABLED,
    DEFAULT_AGENT_AUTO_RETRY_ON_ERROR,
    DEFAULT_AGENT_AUTONOMY_LEVEL,
    DEFAULT_AGENT_BROWSING_ENABLED,
    DEFAULT_AGENT_CLI_MODE,
    DEFAULT_AGENT_COMPLEXITY_ITERATION_MULTIPLIER,
    DEFAULT_AGENT_CONDENSATION_REQUEST_ENABLED,
    DEFAULT_AGENT_CONFIRM_ACTIONS,
    DEFAULT_AGENT_DYNAMIC_ITERATIONS_ENABLED,
    DEFAULT_AGENT_ENABLE_FIRST_TURN_ORIENTATION_PROMPT,
    DEFAULT_AGENT_ERROR_RATE_WINDOW,
    DEFAULT_AGENT_FINISH_ENABLED,
    DEFAULT_AGENT_HISTORY_TRUNCATION_ENABLED,
    DEFAULT_AGENT_HYBRID_RETRIEVAL_ENABLED,
    DEFAULT_AGENT_INTERNAL_TASK_TRACKER_ENABLED,
    DEFAULT_AGENT_MAX_AUTONOMOUS_ITERATIONS,
    DEFAULT_AGENT_MAX_CONSECUTIVE_ERRORS,
    DEFAULT_AGENT_MAX_ERROR_RATE,
    DEFAULT_AGENT_MAX_HIGH_RISK_ACTIONS,
    DEFAULT_AGENT_MAX_STUCK_DETECTIONS,
    DEFAULT_AGENT_MCP_ENABLED,
    DEFAULT_AGENT_MEMORY_ENABLED,
    DEFAULT_AGENT_MEMORY_MAX_THREADS,
    DEFAULT_AGENT_MERGE_CONTROL_SYSTEM_INTO_PRIMARY,
    DEFAULT_AGENT_MIN_ITERATIONS,
    DEFAULT_AGENT_NAME,
    DEFAULT_AGENT_NATIVE_BROWSER_ENABLED,
    DEFAULT_AGENT_PARALLEL_TOOL_SCHEDULING_ENABLED,
    DEFAULT_AGENT_PLAN_MODE_ENABLED,
    DEFAULT_AGENT_PLANNING_COMPLEXITY_THRESHOLD,
    DEFAULT_AGENT_PLANNING_MIDDLEWARE_ENABLED,
    DEFAULT_AGENT_PROMPT_EXTENSIONS_ENABLED,
    DEFAULT_AGENT_REFLECTION_ENABLED,
    DEFAULT_AGENT_REFLECTION_MAX_ATTEMPTS,
    DEFAULT_AGENT_REFLECTION_MIDDLEWARE_ENABLED,
    DEFAULT_AGENT_SIGNAL_PROGRESS_ENABLED,
    DEFAULT_AGENT_SOM_VISUAL_BROWSING_ENABLED,
    DEFAULT_AGENT_STUCK_DETECTION_ENABLED,
    DEFAULT_AGENT_STUCK_THRESHOLD_ITERATIONS,
    DEFAULT_AGENT_SYSTEM_PROMPT_FILENAME,
    DEFAULT_AGENT_THINK_ENABLED,
    DEFAULT_AGENT_VECTOR_MEMORY_ENABLED,
    DEFAULT_AGENT_WARNING_FIRST_TRIP_ENABLED,
    DEFAULT_AGENT_WARNING_FIRST_TRIP_LIMIT,
)
from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.core.config.llm_config import LLMConfig
else:
    LLMConfig = Any  # For runtime when TYPE_CHECKING is False


class AgentConfig(BaseModel, metaclass=CanonicalModelMetaclass):
    """Configuration for an agent.

    Attributes:
        name: Name of the agent to use
        llm_config: LLM configuration for the agent
        memory_max_threads: Maximum number of history items to include in context window
        memory_enabled: Whether to enable conversation memory
        compactor_config: Configuration for conversation memory compactor
        enable_prompt_extensions: Whether to allow agent-specific prompt extensions (agent suffix)
        enable_browsing: Whether to enable browser environment
        enable_auto_lint: Whether to enable automatic linting after edits
        confirm_actions: Whether to require user confirmation before executing actions
        llm_draft_config: LLM configuration for draft operations

    """

    model_config = ConfigDict(extra='forbid')

    name: str = Field(
        default=DEFAULT_AGENT_NAME,
        min_length=1,
        description='Name of the agent to use',
    )
    llm_config: LLMConfig | None = Field(
        default=None, description='LLM configuration for the agent'
    )
    memory_max_threads: int = Field(
        default=DEFAULT_AGENT_MEMORY_MAX_THREADS,
        ge=1,
        description='Maximum number of history items to include in context window',
    )
    memory_enabled: bool = Field(
        default=DEFAULT_AGENT_MEMORY_ENABLED,
        description='Whether to enable conversation memory',
    )
    compactor_config: CompactorConfig = Field(default_factory=AutoCompactorConfig)
    enable_prompt_extensions: bool = Field(
        default=DEFAULT_AGENT_PROMPT_EXTENSIONS_ENABLED
    )
    enable_browsing: bool = Field(default=DEFAULT_AGENT_BROWSING_ENABLED)
    enable_native_browser: bool = Field(
        default=DEFAULT_AGENT_NATIVE_BROWSER_ENABLED,
        description='Expose native browser-use tools (requires optional `browser` dependency group)',
    )
    enable_vector_memory: bool = Field(
        default=DEFAULT_AGENT_VECTOR_MEMORY_ENABLED,
        description='Enable persistent vector memory store',
    )
    enable_hybrid_retrieval: bool = Field(
        default=DEFAULT_AGENT_HYBRID_RETRIEVAL_ENABLED,
        description='Enable hybrid retrieval for vector memory',
    )
    disabled_playbooks: list[str] = Field(
        default_factory=list, description='List of playbooks disabled for this agent'
    )
    enable_auto_lint: bool = Field(default=DEFAULT_AGENT_AUTO_LINT_ENABLED)
    confirm_actions: bool = Field(default=DEFAULT_AGENT_CONFIRM_ACTIONS)
    llm_draft_config: LLMConfig | None = Field(default=None)
    auto_retry_on_error: bool = Field(
        default=DEFAULT_AGENT_AUTO_RETRY_ON_ERROR,
        description='Automatically retry actions when recoverable errors occur',
    )
    autonomy_level: str = Field(
        default=DEFAULT_AGENT_AUTONOMY_LEVEL,
        min_length=1,
        description='Autonomy mode: supervised, balanced, or full',
    )

    # Core tool toggles
    enable_think: bool = Field(
        default=DEFAULT_AGENT_THINK_ENABLED,
        description=(
            'Expose the think tool for explicit reasoning steps (optional; models may reason in prose).'
        ),
    )
    enable_finish: bool = Field(
        default=DEFAULT_AGENT_FINISH_ENABLED,
        description=(
            'Expose the finish tool. Keep enabled: the orchestrator uses it as the normal task-completion '
            'signal (state transitions, validation). Disabling removes a core lifecycle hook unless you '
            'replace it elsewhere.'
        ),
    )
    enable_condensation_request: bool = Field(
        default=DEFAULT_AGENT_CONDENSATION_REQUEST_ENABLED,
        description=(
            'Expose summarize_context so the model can request conversation condensation. Independent of '
            'automatic compaction; default off to reduce redundant tool surface.'
        ),
    )

    # Agent Tools configuration
    enable_terminal: bool = Field(default=True)
    enable_editor: bool = Field(default=True)
    enable_working_memory: bool = Field(default=True)
    enable_lsp_query: bool = Field(default=True)
    enable_signal_progress: bool = Field(default=DEFAULT_AGENT_SIGNAL_PROGRESS_ENABLED)
    enable_swarming: bool = Field(default=False)
    enable_blackboard: bool = Field(default=False)
    enable_verify_file_lines: bool = Field(default=True)
    enable_meta_cognition: bool = Field(default=True)
    enable_checkpoints: bool = Field(default=True)
    enable_parallel_tool_scheduling: bool = Field(
        default=DEFAULT_AGENT_PARALLEL_TOOL_SCHEDULING_ENABLED,
        description=(
            'Enable scheduler-driven parallel execution for tool-action batches '
            'that are explicitly classified as parallel-safe.'
        ),
    )

    # Advanced capabilities
    enable_history_truncation: bool = Field(
        default=DEFAULT_AGENT_HISTORY_TRUNCATION_ENABLED
    )
    enable_plan_mode: bool = Field(
        default=DEFAULT_AGENT_PLAN_MODE_ENABLED,
        description='Enable task planning and decomposition (task tracker tool)',
    )
    enable_mcp: bool = Field(default=DEFAULT_AGENT_MCP_ENABLED)
    enable_auto_planning: bool = Field(
        default=DEFAULT_AGENT_AUTO_PLANNING_ENABLED,
        description='Automatically decompose complex tasks before execution',
    )
    planning_complexity_threshold: int = Field(
        default=DEFAULT_AGENT_PLANNING_COMPLEXITY_THRESHOLD,
        description='Minimum number of distinct requirements to trigger automatic planning',
    )
    enable_reflection: bool = Field(
        default=DEFAULT_AGENT_REFLECTION_ENABLED,
        description='Enable self-reflection before executing actions',
    )
    enable_planning_middleware: bool = Field(
        default=DEFAULT_AGENT_PLANNING_MIDDLEWARE_ENABLED,
        description='Enable planning middleware to analyze incoming tasks before execution',
    )
    enable_reflection_middleware: bool = Field(
        default=DEFAULT_AGENT_REFLECTION_MIDDLEWARE_ENABLED,
        description='Enable reflection middleware to verify actions before execution',
    )
    reflection_max_attempts: int = Field(
        default=DEFAULT_AGENT_REFLECTION_MAX_ATTEMPTS,
        description='Maximum self-correction attempts during reflection',
    )
    enable_dynamic_iterations: bool = Field(
        default=DEFAULT_AGENT_DYNAMIC_ITERATIONS_ENABLED,
        description='Dynamically adjust max_iterations based on task complexity',
    )
    min_iterations: int = Field(
        default=DEFAULT_AGENT_MIN_ITERATIONS,
        description='Minimum iterations for simple tasks',
    )
    max_iterations_override: int | None = Field(
        default=None,
        description='Override max_iterations from AppConfig (None = use AppConfig value)',
    )
    complexity_iteration_multiplier: float = Field(
        default=DEFAULT_AGENT_COMPLEXITY_ITERATION_MULTIPLIER,
        description='Iterations = complexity_score * multiplier (capped at max_iterations)',
    )
    max_autonomous_iterations: int = Field(
        default=DEFAULT_AGENT_MAX_AUTONOMOUS_ITERATIONS,
        description='Maximum self-directed iterations when autonomy is full',
    )
    stuck_detection_enabled: bool = Field(
        default=DEFAULT_AGENT_STUCK_DETECTION_ENABLED,
        description='Enable stuck detection when autonomy is full',
    )
    stuck_threshold_iterations: int = Field(
        default=DEFAULT_AGENT_STUCK_THRESHOLD_ITERATIONS,
        description='Number of iterations without progress before triggering stuck handling',
    )
    enable_internal_task_tracker: bool = Field(
        default=DEFAULT_AGENT_INTERNAL_TASK_TRACKER_ENABLED,
        description='Enable the internal task progress tracker tool',
    )

    # Memory features
    enable_som_visual_browsing: bool = Field(
        default=DEFAULT_AGENT_SOM_VISUAL_BROWSING_ENABLED,
        description='Enable SOM (Self-Organizing Map) visual browsing',
    )

    # Prompt management
    system_prompt_filename: str = Field(
        default=DEFAULT_AGENT_SYSTEM_PROMPT_FILENAME,
        min_length=1,
        description='Filename for the system prompt template',
    )
    enable_circuit_breaker: bool = Field(
        default=True,
        description=(
            'Enable the circuit breaker to auto-pause the agent after '
            'repeated failures (consecutive errors, stuck detections, '
            'high-risk actions). Disable only for debugging.'
        ),
    )
    warning_first_trip_enabled: bool = Field(
        default=DEFAULT_AGENT_WARNING_FIRST_TRIP_ENABLED,
        description=(
            'When true, circuit/stuck trips are first surfaced as structured '
            'agent guidance before hard pause/stop is enforced.'
        ),
    )
    warning_first_trip_limit: int = Field(
        default=DEFAULT_AGENT_WARNING_FIRST_TRIP_LIMIT,
        ge=1,
        description='Number of warning-only circuit trips before hard enforcement',
    )
    enable_graceful_shutdown: bool = Field(
        default=True,
        description=(
            'When the iteration or budget limit is hit, give the agent one '
            'final turn to save work and summarize progress instead of '
            'stopping abruptly.'
        ),
    )
    cli_mode: bool = Field(
        default=DEFAULT_AGENT_CLI_MODE,
        description='Whether the agent is running in CLI mode',
    )
    enable_first_turn_orientation_prompt: bool = Field(
        default=DEFAULT_AGENT_ENABLE_FIRST_TURN_ORIENTATION_PROMPT,
        description=(
            'Inject an opt-in first-turn orientation block in the per-turn control message'
        ),
    )
    merge_control_system_into_primary: bool = Field(
        default=DEFAULT_AGENT_MERGE_CONTROL_SYSTEM_INTO_PRIMARY,
        description=(
            'Append APP control/status text to the first system message instead of '
            'inserting a second system message (some providers handle a single system '
            'message better)'
        ),
    )
    max_consecutive_errors: int = Field(
        default=DEFAULT_AGENT_MAX_CONSECUTIVE_ERRORS,
        ge=1,
        description='Circuit breaker threshold for consecutive errors',
    )
    max_high_risk_actions: int = Field(
        default=DEFAULT_AGENT_MAX_HIGH_RISK_ACTIONS,
        ge=1,
        description='Circuit breaker threshold for high-risk actions',
    )
    max_stuck_detections: int = Field(
        default=DEFAULT_AGENT_MAX_STUCK_DETECTIONS,
        ge=1,
        description='Circuit breaker threshold for stuck-loop detections',
    )
    max_error_rate: float = Field(
        default=DEFAULT_AGENT_MAX_ERROR_RATE,
        ge=0.0,
        le=1.0,
        description='Circuit breaker error-rate threshold over rolling window',
    )
    error_rate_window: int = Field(
        default=DEFAULT_AGENT_ERROR_RATE_WINDOW,
        ge=5,
        description='Rolling window size for circuit breaker error-rate checks',
    )

    @model_validator(mode='before')
    @classmethod
    def _drop_legacy_enable_prompt_caching(cls, data: Any) -> Any:
        """Normalize legacy field names before model validation."""
        if isinstance(data, dict):
            data = dict(data)
            data.pop('enable_prompt_caching', None)
            data.pop('enable_web_search', None)
        return data

    @field_validator('name', 'autonomy_level', 'system_prompt_filename')
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='field')

    def get_llm_config(self) -> LLMConfig | None:
        """Get the default LLM configuration for this agent.

        Returns:
            LLM configuration to use when none is specified

        """
        # If a specific LLM config override is provided, use that
        if self.llm_config:
            return self.llm_config
        # Otherwise fall back to the default llm key
        return None

    @property
    def resolved_system_prompt_filename(self) -> str:
        """Return a safe system prompt filename for PromptManager."""
        filename = getattr(self, 'system_prompt_filename', None)
        if not filename or not isinstance(filename, str):
            return 'system_prompt'
        return filename

    @classmethod
    def from_toml_section(cls, data: dict) -> dict[str, AgentConfig]:
        """Build mapping from agent id to agent config.

        {
            "manager": AgentConfig(...)
        }
        """
        agent_mapping: dict[str, AgentConfig] = {}
        base_data, custom_sections = cls._separate_base_and_custom_sections(data)
        schema_version = base_data.pop('schema_version', None)

        if schema_version is None:
            config_telemetry.record_schema_missing()
            logger.warning(
                'Agent configuration missing schema_version; expected %s.',
                CURRENT_AGENT_CONFIG_SCHEMA_VERSION,
            )
        elif str(schema_version) != CURRENT_AGENT_CONFIG_SCHEMA_VERSION:
            config_telemetry.record_schema_mismatch(str(schema_version))
            logger.warning(
                'Agent configuration schema_version mismatch (got %s, expected %s).',
                schema_version,
                CURRENT_AGENT_CONFIG_SCHEMA_VERSION,
            )

        base_config = cls._create_base_config(base_data)
        agent_mapping['agent'] = base_config
        errors: list[str] = []

        for name, overrides in custom_sections.items():
            try:
                custom_config = cls._create_custom_config(name, base_config, overrides)
                agent_mapping[name] = custom_config
            except (ValidationError, TypeError, ValueError, KeyError) as e:
                config_telemetry.record_invalid_agent(name)
                errors.append(f'[{name}] {e}')

        if errors:
            combined = '\n - '.join(errors)
            raise ValueError(f'Invalid custom agent configuration(s):\n - {combined}')

        return agent_mapping

    @staticmethod
    def _separate_base_and_custom_sections(data: dict) -> tuple[dict, dict[str, dict]]:
        """Separate base agent config from custom agent configs.

        Args:
            data: Raw configuration dictionary

        Returns:
            Tuple of (base_config_dict, {custom_name: overrides_dict})

        """
        base_data = {}
        custom_sections: dict[str, dict] = {}

        for key, value in data.items():
            if isinstance(value, dict) and key not in [
                'llm_config',
                'compactor_config',
                'llm_draft_config',
            ]:
                # This is a custom agent section like [agent.Navigator]
                custom_sections[key] = value
            else:
                # This is part of the base config
                base_data[key] = value

        return base_data, custom_sections

    @classmethod
    def _create_base_config(cls, base_data: dict) -> AgentConfig:
        """Create the base agent configuration.

        Args:
            base_data: Dictionary containing base configuration values

        Returns:
            AgentConfig instance with base settings

        """
        valid_fields = set(cls.model_fields.keys())
        invalid_fields = {k for k in base_data if k not in valid_fields}
        if invalid_fields:
            logger.warning(
                'Ignoring unknown agent config field(s) in base config: %s',
                sorted(invalid_fields),
            )
            base_data = {k: v for k, v in base_data.items() if k in valid_fields}

        try:
            return cls(**base_data)
        except ValidationError as exc:
            # For base config, we try to recover by filtering out invalid values
            logger.warning(
                'Invalid base agent configuration values: %s. Using defaults for those fields.',
                exc,
            )

            # Create a dict with only valid types by trying to validate each field
            safe_data = {}
            for field_name, value in base_data.items():
                try:
                    # Validate a dummy object with just this field
                    cls.model_validate({field_name: value})
                    safe_data[field_name] = value
                except ValidationError:
                    logger.warning(
                        "Value '%s' for field '%s' is invalid, using default.",
                        value,
                        field_name,
                    )

            return cls(**safe_data)

    @classmethod
    def _create_custom_config(
        cls,
        name: str,
        base_config: AgentConfig,
        overrides: dict,
    ) -> AgentConfig:
        """Create a custom agent configuration by merging overrides with base config.

        Args:
            name: Name for the custom agent
            base_config: Base configuration to extend
            overrides: Dictionary of values to override

        Returns:
            AgentConfig with merged settings, or None if invalid

        """
        # Validate that overrides only contain valid fields
        valid_fields = set(cls.model_fields.keys())
        invalid_fields = {k for k in overrides if k not in valid_fields}

        if invalid_fields:
            logger.warning(
                "Ignoring unknown field(s) for agent '%s': %s",
                name,
                sorted(invalid_fields),
            )
            overrides = {k: v for k, v in overrides.items() if k in valid_fields}

        # Filter out invalid override values
        safe_overrides = {}
        for field_name, value in overrides.items():
            try:
                # Validate a dummy object with just this field
                cls.model_validate({field_name: value})
                safe_overrides[field_name] = value
            except ValidationError:
                logger.warning(
                    "Value '%s' for field '%s' in agent '%s' is invalid, using default.",
                    value,
                    field_name,
                    name,
                )

        # Set the custom name
        safe_overrides['name'] = name

        try:
            # Create a new config by copying base and applying safe overrides
            return base_config.model_copy(update=safe_overrides)
        except Exception as e:
            logger.warning("Failed to create custom config for agent '%s': %s", name, e)
            return base_config.model_copy(update={'name': name})


# Rebuild the model after all dependencies are loaded to resolve forward references
AgentConfig.model_rebuild()
