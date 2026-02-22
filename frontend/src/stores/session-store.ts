import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import { AgentState } from "@/types/agent";
import type { ForgeEvent, ActionEvent, ObservationEvent } from "@/types/events";
import { ObservationType, ActionType } from "@/types/agent";

export interface SessionState {
  conversationId: string | null;
  events: ForgeEvent[];
  agentState: AgentState;
  latestEventId: number;
  streamingContent: string;
  isConnected: boolean;
  isReconnecting: boolean;

  // Actions
  setConversation: (id: string) => void;
  clearSession: () => void;
  addEvent: (event: ForgeEvent) => void;
  setAgentState: (state: AgentState) => void;
  setConnected: (connected: boolean) => void;
  setReconnecting: (reconnecting: boolean) => void;
  appendStreamingChunk: (chunk: string) => void;
  clearStreaming: () => void;
}

export const useSessionStore = create<SessionState>()(
  immer((set) => ({
    conversationId: null,
    events: [],
    agentState: AgentState.LOADING,
    latestEventId: -1,
    streamingContent: "",
    isConnected: false,
    isReconnecting: false,

    setConversation: (id) =>
      set((state) => {
        state.conversationId = id;
        state.events = [];
        state.agentState = AgentState.LOADING;
        state.latestEventId = -1;
        state.streamingContent = "";
      }),

    clearSession: () =>
      set((state) => {
        state.conversationId = null;
        state.events = [];
        state.agentState = AgentState.LOADING;
        state.latestEventId = -1;
        state.streamingContent = "";
        state.isConnected = false;
      }),

    addEvent: (event) =>
      set((state) => {
        // Handle agent state changes
        if ("observation" in event && event.observation === ObservationType.AGENT_STATE_CHANGED) {
          const obs = event as ObservationEvent;
          const newState = obs.extras?.agent_state as AgentState | undefined;
          if (newState) {
            state.agentState = newState;
          }
        }

        // Handle streaming chunks — append to buffer instead of events list
        if ("action" in event && (event as ActionEvent).action === ActionType.STREAMING_CHUNK) {
          const chunk = (event as ActionEvent).args?.chunk;
          if (typeof chunk === "string") {
            state.streamingContent += chunk;
          }
          // Don't add streaming chunks to events array
          return;
        }

        // When a message action arrives after streaming, finalize the streaming content
        if ("action" in event && (event as ActionEvent).action === ActionType.MESSAGE) {
          if (state.streamingContent) {
            state.streamingContent = "";
          }
        }

        state.events.push(event);
        if (event.id > state.latestEventId) {
          state.latestEventId = event.id;
        }
      }),

    setAgentState: (agentState) =>
      set((state) => {
        state.agentState = agentState;
      }),

    setConnected: (connected) =>
      set((state) => {
        state.isConnected = connected;
      }),

    setReconnecting: (reconnecting) =>
      set((state) => {
        state.isReconnecting = reconnecting;
      }),

    appendStreamingChunk: (chunk) =>
      set((state) => {
        state.streamingContent += chunk;
      }),

    clearStreaming: () =>
      set((state) => {
        state.streamingContent = "";
      }),
  })),
);
