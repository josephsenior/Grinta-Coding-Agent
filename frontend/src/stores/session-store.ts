import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import { AgentState } from "@/types/agent";
import type { ForgeEvent, ActionEvent, ObservationEvent } from "@/types/events";
import { ObservationType, ActionType } from "@/types/agent";
import { isRecoverableTransientForgeEvent } from "@/lib/transient-session-errors";
import {
  isNotifyUiOnlyErrorEvent,
  toastNotifyUiOnlyError,
} from "@/lib/error-observation";

function recomputeAgentStateFromEvents(events: ForgeEvent[]): AgentState {
  let state = AgentState.LOADING;
  for (const ev of events) {
    if ("observation" in ev && ev.observation === ObservationType.AGENT_STATE_CHANGED) {
      const obs = ev as ObservationEvent;
      const next = obs.extras?.agent_state as AgentState | undefined;
      if (next) state = next;
    }
  }
  return state;
}

export interface SessionState {
  conversationId: string | null;
  events: ForgeEvent[];
  /** Event IDs handled as toast-only or skipped on history merge — not in `events`, but must dedupe socket replay. */
  offTimelineEventIds: Set<number>;
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
  /** Merge events from REST history; dedupes by id, keeps order by id. */
  mergeHistoricalEvents: (incoming: ForgeEvent[]) => void;
  /** Remove connectivity / startup error cards superseded after backend recovery. */
  pruneRecoverableTransientErrors: () => void;
}

export const useSessionStore = create<SessionState>()(
  immer((set) => ({
    conversationId: null,
    events: [],
    offTimelineEventIds: new Set<number>(),
    agentState: AgentState.LOADING,
    latestEventId: -1,
    streamingContent: "",
    isConnected: false,
    isReconnecting: false,

    setConversation: (id) =>
      set((state) => {
        // Re-entering the same chat (e.g. sidebar navigation) must keep events;
        // clearing here + stale latestEventIdRef caused replay to be deduped away.
        if (state.conversationId === id) return;
        state.conversationId = id;
        state.events = [];
        state.offTimelineEventIds.clear();
        state.agentState = AgentState.LOADING;
        state.latestEventId = -1;
        state.streamingContent = "";
      }),

    clearSession: () =>
      set((state) => {
        state.conversationId = null;
        state.events = [];
        state.offTimelineEventIds.clear();
        state.agentState = AgentState.LOADING;
        state.latestEventId = -1;
        state.streamingContent = "";
        state.isConnected = false;
      }),

    addEvent: (event) =>
      set((state) => {
        const eid =
          typeof event.id === "number" && Number.isFinite(event.id)
            ? event.id
            : Number(event.id);
        if (!Number.isFinite(eid) || eid < 0) return;

        const ev: ForgeEvent =
          eid !== event.id ? ({ ...event, id: eid } as ForgeEvent) : event;

        // Handle agent state changes
        if ("observation" in ev && ev.observation === ObservationType.AGENT_STATE_CHANGED) {
          const obs = ev as ObservationEvent;
          const newState = obs.extras?.agent_state as AgentState | undefined;
          if (newState) {
            state.agentState = newState;
          }
        }

        // Handle streaming chunks — append to buffer instead of events list
        if ("action" in ev && (ev as ActionEvent).action === ActionType.STREAMING_CHUNK) {
          const chunk = (ev as ActionEvent).args?.chunk;
          if (typeof chunk === "string") {
            state.streamingContent += chunk;
          }
          if (eid > state.latestEventId) {
            state.latestEventId = eid;
          }
          return;
        }

        // Drop duplicate deliveries (e.g. REST hydrate + socket replay).
        if (
          state.events.some((x) => Number(x.id) === eid) ||
          state.offTimelineEventIds.has(eid)
        ) {
          return;
        }

        if (isNotifyUiOnlyErrorEvent(ev)) {
          toastNotifyUiOnlyError(ev as ObservationEvent);
          state.offTimelineEventIds.add(eid);
          if (eid > state.latestEventId) {
            state.latestEventId = eid;
          }
          return;
        }

        // When a message action arrives after streaming, finalize the streaming content
        if ("action" in ev && (ev as ActionEvent).action === ActionType.MESSAGE) {
          if (state.streamingContent) {
            state.streamingContent = "";
          }
        }

        state.events.push(ev);
        if (eid > state.latestEventId) {
          state.latestEventId = eid;
        }
      }),

    mergeHistoricalEvents: (incoming) =>
      set((state) => {
        const existingIds = new Set([
          ...state.events.map((e) => Number(e.id)),
          ...state.offTimelineEventIds,
        ]);
        const sorted = [...incoming].sort((a, b) => Number(a.id) - Number(b.id));

        for (const raw of sorted) {
          const eid =
            typeof raw.id === "number" && Number.isFinite(raw.id) ? raw.id : Number(raw.id);
          if (!Number.isFinite(eid) || eid < 0) continue;

          const ev: ForgeEvent = eid !== raw.id ? ({ ...raw, id: eid } as ForgeEvent) : raw;

          if ("observation" in ev && ev.observation === ObservationType.AGENT_STATE_CHANGED) {
            const obs = ev as ObservationEvent;
            const newState = obs.extras?.agent_state as AgentState | undefined;
            if (newState) {
              state.agentState = newState;
            }
          }

          if ("action" in ev && (ev as ActionEvent).action === ActionType.STREAMING_CHUNK) {
            // Persisted chunks: advance cursor only; do not rebuild stale streaming buffer.
            if (eid > state.latestEventId) {
              state.latestEventId = eid;
            }
            continue;
          }

          if (existingIds.has(eid)) continue;

          if (isNotifyUiOnlyErrorEvent(ev)) {
            existingIds.add(eid);
            state.offTimelineEventIds.add(eid);
            if (eid > state.latestEventId) {
              state.latestEventId = eid;
            }
            continue;
          }

          if ("action" in ev && (ev as ActionEvent).action === ActionType.MESSAGE) {
            if (state.streamingContent) {
              state.streamingContent = "";
            }
          }

          state.events.push(ev);
          existingIds.add(eid);
          if (eid > state.latestEventId) {
            state.latestEventId = eid;
          }
        }

        state.events.sort((a, b) => Number(a.id) - Number(b.id));
      }),

    pruneRecoverableTransientErrors: () =>
      set((state) => {
        const next = state.events.filter((ev) => !isRecoverableTransientForgeEvent(ev));
        if (next.length === state.events.length) return;
        state.events = next;
        state.agentState = recomputeAgentStateFromEvents(next);
        state.latestEventId = next.reduce((m, e) => Math.max(m, Number(e.id)), -1);
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
