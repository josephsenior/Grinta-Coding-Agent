/** Conversation status — mirrors backend ConversationStatus enum. */
export enum ConversationStatus {
  STARTING = "starting",
  RUNNING = "running",
  STOPPED = "stopped",
  PAUSED = "paused",
  ARCHIVED = "archived",
  UNKNOWN = "unknown",
}

/** Conversation metadata returned by the REST API. */
export interface ConversationInfo {
  conversation_id: string;
  title: string;
  last_updated_at: string | null;
  status: ConversationStatus;
  runtime_status: string | null;
  agent_state: string | null;
  selected_repository: string | null;
  selected_branch: string | null;
  num_connections: number;
  created_at: string;
}

/** Paginated conversation list response. */
export interface ConversationListResponse {
  results: ConversationInfo[];
  next_page_id: string | null;
}

/** Payload for creating a new conversation. */
export interface CreateConversationRequest {
  initial_message?: string;
  selected_repository?: string;
  selected_branch?: string;
}
