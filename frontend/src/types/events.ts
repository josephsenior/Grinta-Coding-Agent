import type { ActionType, ObservationType, AgentState, ActionSecurityRisk } from "./agent";

/** Base fields present on every event emitted via Socket.IO. */
export interface ForgeEventBase {
  id: number;
  timestamp: string;
  source: "agent" | "user" | "environment";
  message: string;
  cause?: number;
}

/** An action event (agent or user initiated). */
export interface ActionEvent extends ForgeEventBase {
  action: ActionType;
  args: Record<string, unknown>;
  security_risk?: ActionSecurityRisk;
  confirmation_status?: string;
}

/** An observation event (result of an action). */
export interface ObservationEvent extends ForgeEventBase {
  observation: ObservationType;
  content: string;
  extras: Record<string, unknown>;
}

/** Agent state change observation. */
export interface AgentStateChangedEvent extends ForgeEventBase {
  observation: ObservationType.AGENT_STATE_CHANGED;
  extras: {
    agent_state: AgentState;
    [key: string]: unknown;
  };
}

/** Streaming chunk for real-time token display. */
export interface StreamingChunkEvent extends ForgeEventBase {
  action: ActionType.STREAMING_CHUNK;
  args: {
    chunk: string;
    [key: string]: unknown;
  };
}

/** Discriminated union of all forge events. */
export type ForgeEvent = ActionEvent | ObservationEvent | AgentStateChangedEvent | StreamingChunkEvent;

/** User action sent to the server via Socket.IO. */
export interface UserAction {
  action: string;
  args: Record<string, unknown>;
}
