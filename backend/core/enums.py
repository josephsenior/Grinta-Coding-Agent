"""Core enumeration types for Forge.

Extracted from constants.py to keep single-responsibility modules.
"""

from enum import Enum


class QuotaPlan(str, Enum):
    """User quota plans."""

    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"
    UNLIMITED = "unlimited"


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class ErrorSeverity(str, Enum):
    """Error severity levels for UX presentation."""

    INFO = "info"  # ℹ️ Informational (blue)
    WARNING = "warning"  # ⚠️ Warning (yellow)
    ERROR = "error"  # ❌ Error (red)
    CRITICAL = "critical"  # 🚨 Critical (red + urgent)


class ErrorCategory(str, Enum):
    """Error categories for better UX grouping."""

    USER_INPUT = "user_input"  # User made a mistake
    SYSTEM = "system"  # System/infrastructure issue
    RATE_LIMIT = "rate_limit"  # Rate limiting/quota
    AUTHENTICATION = "authentication"  # Auth/permissions
    NETWORK = "network"  # Network/connectivity
    AI_MODEL = "ai_model"  # LLM/AI model issue
    CONFIGURATION = "configuration"  # Config/setup issue


class ContentType(str, Enum):
    """Content type enum for message content."""

    TEXT = "text"
    IMAGE_URL = "image_url"
    __test__ = False


class ActionType(str, Enum):
    """Enum defining all possible agent action types."""

    MESSAGE = "message"
    SYSTEM = "system"
    START = "start"
    READ = "read"
    WRITE = "write"
    EDIT = "edit"
    RUN = "run"
    BROWSE = "browse"
    BROWSE_INTERACTIVE = "browse_interactive"
    MCP = "call_tool_mcp"
    THINK = "think"
    FINISH = "finish"
    REJECT = "reject"
    NULL = "null"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    CHANGE_AGENT_STATE = "change_agent_state"
    PUSH = "push"
    SEND_PR = "send_pr"
    RECALL = "recall"
    CONDENSATION = "condensation"
    CONDENSATION_REQUEST = "condensation_request"
    TASK_TRACKING = "task_tracking"
    STREAMING_CHUNK = "streaming_chunk"


class LifecyclePhase(str, Enum):
    """High-level lifecycle phases for the AgentController.

    Unlike :class:`AgentState` (which tracks the agent's *logical* state
    within a conversation), ``LifecyclePhase`` tracks the controller
    *infrastructure* lifecycle::

        INITIALIZING → ACTIVE → CLOSING → CLOSED

    Once CLOSED, the controller cannot be re-used.
    """

    INITIALIZING = "initializing"
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"


class AgentState(str, Enum):
    """Enum defining all possible agent lifecycle states."""

    LOADING = "loading"
    RUNNING = "running"
    AWAITING_USER_INPUT = "awaiting_user_input"
    PAUSED = "paused"
    STOPPED = "stopped"
    FINISHED = "finished"
    REJECTED = "rejected"
    ERROR = "error"
    AWAITING_USER_CONFIRMATION = "awaiting_user_confirmation"
    USER_CONFIRMED = "user_confirmed"
    USER_REJECTED = "user_rejected"
    RATE_LIMITED = "rate_limited"


class ObservationType(str, Enum):
    """Enum defining all possible observation types."""

    READ = "read"
    WRITE = "write"
    EDIT = "edit"
    BROWSE = "browse"
    RUN = "run"
    CHAT = "chat"
    MESSAGE = "message"
    ERROR = "error"
    SUCCESS = "success"
    NULL = "null"
    THINK = "think"
    AGENT_STATE_CHANGED = "agent_state_changed"
    USER_REJECTED = "user_rejected"
    CONDENSE = "condense"
    RECALL = "recall"
    MCP = "mcp"
    DOWNLOAD = "download"
    TASK_TRACKING = "task_tracking"
    SERVER_READY = "server_ready"
    RECALL_FAILURE = "recall_failure"
    STATUS = "status"


class ExitReason(str, Enum):
    """Enum defining reasons why agent execution ended.

    Used to distinguish between normal completion, interruption, and errors.
    """

    INTENTIONAL = "intentional"
    INTERRUPTED = "interrupted"
    ERROR = "error"
    __test__ = False


class ActionConfirmationStatus(str, Enum):
    """Status of action confirmation in confirmation mode."""

    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    AWAITING_CONFIRMATION = "awaiting_confirmation"


class ActionSecurityRisk(int, Enum):
    """Security risk level for actions (from security analyzer)."""

    UNKNOWN = -1
    LOW = 0
    MEDIUM = 1
    HIGH = 2


class AppMode(str, Enum):
    """Enumerate supported deployment modes for the Forge server."""

    OSS = "oss"
    SAAS = "saas"
    __test__ = False


class EventVersion(str, Enum):
    """Schema version for event serialization."""

    V1 = "1.0.0"
    V2 = "2.0.0"  # Reserved for future use


class EventSource(str, Enum):
    """Canonical originator categories for events."""

    AGENT = "agent"
    USER = "user"
    ENVIRONMENT = "environment"
    __test__ = False


class FileEditSource(str, Enum):
    """Enumerates subsystems that can perform file edit operations."""

    LLM_BASED_EDIT = "llm_based_edit"
    FILE_EDITOR = "file_editor"
    __test__ = False


class FileReadSource(str, Enum):
    """Enumerates subsystems that can read files during execution."""

    FILE_EDITOR = "file_editor"
    DEFAULT = "default"
    __test__ = False


class RecallType(str, Enum):
    """The type of information that can be retrieved from playbooks."""

    WORKSPACE_CONTEXT = "workspace_context"
    KNOWLEDGE = "knowledge"
    __test__ = False


class RetryStrategy(str, Enum):
    """Retry strategies for different failure scenarios."""

    EXPONENTIAL = "exponential"  # Exponential backoff with jitter
    LINEAR = "linear"  # Linear backoff
    FIXED = "fixed"  # Fixed delay
    IMMEDIATE = "immediate"  # No delay between retries


class RuntimeStatus(str, Enum):
    """Lifecycle states emitted by runtime implementations."""

    UNKNOWN = "UNKNOWN"
    STOPPED = "STATUS$STOPPED"
    BUILDING_RUNTIME = "STATUS$BUILDING_RUNTIME"
    STARTING_RUNTIME = "STATUS$STARTING_RUNTIME"
    RUNTIME_STARTED = "STATUS$RUNTIME_STARTED"
    SETTING_UP_WORKSPACE = "STATUS$SETTING_UP_WORKSPACE"
    SETTING_UP_GIT_HOOKS = "STATUS$SETTING_UP_GIT_HOOKS"
    READY = "STATUS$READY"
    ERROR = "STATUS$ERROR"
    ERROR_RUNTIME_DISCONNECTED = "STATUS$ERROR_RUNTIME_DISCONNECTED"
    ERROR_LLM_AUTHENTICATION = "STATUS$ERROR_LLM_AUTHENTICATION"
    ERROR_LLM_SERVICE_UNAVAILABLE = "STATUS$ERROR_LLM_SERVICE_UNAVAILABLE"
    ERROR_LLM_INTERNAL_SERVER_ERROR = "STATUS$ERROR_LLM_INTERNAL_SERVER_ERROR"
    ERROR_LLM_OUT_OF_CREDITS = "STATUS$ERROR_LLM_OUT_OF_CREDITS"
    ERROR_LLM_CONTENT_POLICY_VIOLATION = "STATUS$ERROR_LLM_CONTENT_POLICY_VIOLATION"
    AGENT_RATE_LIMITED_STOPPED_MESSAGE = (
        "CHAT_INTERFACE$AGENT_RATE_LIMITED_STOPPED_MESSAGE"
    )
    GIT_PROVIDER_AUTHENTICATION_ERROR = "STATUS$GIT_PROVIDER_AUTHENTICATION_ERROR"
    LLM_RETRY = "STATUS$LLM_RETRY"
    ERROR_MEMORY = "STATUS$ERROR_MEMORY"
    __test__ = False
