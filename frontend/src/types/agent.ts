/** Agent lifecycle states — mirrors backend AgentState enum. */
export enum AgentState {
  LOADING = "loading",
  RUNNING = "running",
  AWAITING_USER_INPUT = "awaiting_user_input",
  PAUSED = "paused",
  STOPPED = "stopped",
  FINISHED = "finished",
  REJECTED = "rejected",
  ERROR = "error",
  AWAITING_USER_CONFIRMATION = "awaiting_user_confirmation",
  USER_CONFIRMED = "user_confirmed",
  USER_REJECTED = "user_rejected",
  RATE_LIMITED = "rate_limited",
}

/** Agent action types — mirrors backend ActionType enum. */
export enum ActionType {
  MESSAGE = "message",
  SYSTEM = "system",
  START = "start",
  READ = "read",
  WRITE = "write",
  EDIT = "edit",
  RUN = "run",
  TERMINAL_RUN = "terminal_run",
  TERMINAL_INPUT = "terminal_input",
  TERMINAL_READ = "terminal_read",
  BROWSE = "browse",
  BROWSE_INTERACTIVE = "browse_interactive",
  MCP = "call_tool_mcp",
  THINK = "think",
  FINISH = "finish",
  REJECT = "reject",
  NULL = "null",
  PAUSE = "pause",
  RESUME = "resume",
  STOP = "stop",
  CHANGE_AGENT_STATE = "change_agent_state",
  PUSH = "push",
  SEND_PR = "send_pr",
  RECALL = "recall",
  CONDENSATION = "condensation",
  CONDENSATION_REQUEST = "condensation_request",
  SUMMARIZE_CONTEXT = "summarize_context",
  TASK_TRACKING = "task_tracking",
  STREAMING_CHUNK = "streaming_chunk",
  UNCERTAINTY = "uncertainty",
  PROPOSAL = "proposal",
  CLARIFICATION = "clarification",
  ESCALATE = "escalate",
  DELEGATE_TASK = "delegate_task",
}

/** Observation types — mirrors backend ObservationType enum. */
export enum ObservationType {
  READ = "read",
  WRITE = "write",
  EDIT = "edit",
  BROWSE = "browse",
  RUN = "run",
  CHAT = "chat",
  MESSAGE = "message",
  ERROR = "error",
  SUCCESS = "success",
  NULL = "null",
  THINK = "think",
  AGENT_STATE_CHANGED = "agent_state_changed",
  USER_REJECTED = "user_rejected",
  CONDENSE = "condense",
  RECALL = "recall",
  MCP = "mcp",
  DOWNLOAD = "download",
  TASK_TRACKING = "task_tracking",
  SERVER_READY = "server_ready",
  RECALL_FAILURE = "recall_failure",
  STATUS = "status",
  TERMINAL = "terminal",
  DELEGATE_TASK_RESULT = "delegate_task_result",
}

/** Security risk level for actions. */
export enum ActionSecurityRisk {
  UNKNOWN = -1,
  LOW = 0,
  MEDIUM = 1,
  HIGH = 2,
}

/** Error severity levels. */
export enum ErrorSeverity {
  INFO = "info",
  WARNING = "warning",
  ERROR = "error",
  CRITICAL = "critical",
}

/** Error categories. */
export enum ErrorCategory {
  USER_INPUT = "user_input",
  SYSTEM = "system",
  RATE_LIMIT = "rate_limit",
  AUTHENTICATION = "authentication",
  NETWORK = "network",
  AI_MODEL = "ai_model",
  CONFIGURATION = "configuration",
}

/** Runtime lifecycle statuses. */
export enum RuntimeStatus {
  UNKNOWN = "UNKNOWN",
  STOPPED = "STATUS$STOPPED",
  BUILDING_RUNTIME = "STATUS$BUILDING_RUNTIME",
  STARTING_RUNTIME = "STATUS$STARTING_RUNTIME",
  RUNTIME_STARTED = "STATUS$RUNTIME_STARTED",
  SETTING_UP_WORKSPACE = "STATUS$SETTING_UP_WORKSPACE",
  SETTING_UP_GIT_HOOKS = "STATUS$SETTING_UP_GIT_HOOKS",
  READY = "STATUS$READY",
  ERROR = "STATUS$ERROR",
  ERROR_RUNTIME_DISCONNECTED = "STATUS$ERROR_RUNTIME_DISCONNECTED",
  ERROR_LLM_AUTHENTICATION = "STATUS$ERROR_LLM_AUTHENTICATION",
  ERROR_LLM_SERVICE_UNAVAILABLE = "STATUS$ERROR_LLM_SERVICE_UNAVAILABLE",
  ERROR_LLM_INTERNAL_SERVER_ERROR = "STATUS$ERROR_LLM_INTERNAL_SERVER_ERROR",
  ERROR_LLM_OUT_OF_CREDITS = "STATUS$ERROR_LLM_OUT_OF_CREDITS",
  ERROR_LLM_CONTENT_POLICY_VIOLATION = "STATUS$ERROR_LLM_CONTENT_POLICY_VIOLATION",
  AGENT_RATE_LIMITED = "CHAT_INTERFACE$AGENT_RATE_LIMITED_STOPPED_MESSAGE",
  GIT_PROVIDER_AUTH_ERROR = "STATUS$GIT_PROVIDER_AUTHENTICATION_ERROR",
  LLM_RETRY = "STATUS$LLM_RETRY",
  ERROR_MEMORY = "STATUS$ERROR_MEMORY",
}

/** Confirmation status for actions. */
export enum ActionConfirmationStatus {
  CONFIRMED = "confirmed",
  REJECTED = "rejected",
  AWAITING_CONFIRMATION = "awaiting_confirmation",
}
