import { useEffect, useRef, useCallback } from "react";
import { useSessionStore } from "@/stores/session-store";
import { useContextPanelStore } from "@/stores/context-panel-store";
import {
  connectSocket,
  disconnectSocket,
  registerForgeEventListener,
} from "@/socket/client";
import {
  fetchAllConversationEvents,
  fetchConversationEventsAfter,
} from "@/api/conversation-events";
import { queryClient } from "@/lib/query-client";
import { toast } from "sonner";
import { SUSTAINED_DISCONNECT_NOTICE_MS } from "@/lib/constants";

/**
 * Manages the Socket.IO lifecycle for a conversation.
 * Handles connect, disconnect, reconnection with replay, and event deduplication.
 */
export function useSocket(conversationId: string | undefined) {
  const {
    latestEventId,
    setConversation,
    addEvent,
    setConnected,
    setReconnecting,
    clearStreaming,
    mergeHistoricalEvents,
  } = useSessionStore();

  // Keep latestEventId in a ref so reconnection always uses current value.
  // Reset to -1 when conversation changes so new-conversation events are not
  // filtered out by stale IDs from the previous conversation.
  const conversationIdRef = useRef(conversationId);
  const latestEventIdRef = useRef(latestEventId);
  if (conversationId !== conversationIdRef.current) {
    conversationIdRef.current = conversationId;
    latestEventIdRef.current = -1;
  } else if (latestEventId > latestEventIdRef.current) {
    latestEventIdRef.current = latestEventId;
  }

  // Track whether this is the initial mount to avoid double-connect in StrictMode
  const connectedRef = useRef(false);

  const disconnectToastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const userNotifiedDisconnectRef = useRef(false);

  const connect = useCallback(
    (convId: string, fromEventId: number) => {
      const socket = connectSocket({
        conversationId: convId,
        latestEventId: fromEventId,
      });

      const offForge = registerForgeEventListener(socket, (event) => {
        if (event.id < 0) return;

        if (event.id <= latestEventIdRef.current) return;

        const gap = event.id - latestEventIdRef.current;
        if (latestEventIdRef.current >= 0 && gap > 50) {
          console.warn(
            `[forge] Event gap detected: expected ~${latestEventIdRef.current + 1}, got ${event.id} (gap=${gap}). Some history may be missing.`,
          );
        }

        latestEventIdRef.current = event.id;
        addEvent(event);
      });

      socket.on("connect", () => {
        setConnected(true);
        setReconnecting(false);
      });

      socket.on("disconnect", (reason) => {
        setConnected(false);
        // Intentional client teardown (e.g. leaving the chat) — no toast.
        if (reason === "io client disconnect") return;

        if (disconnectToastTimerRef.current) {
          clearTimeout(disconnectToastTimerRef.current);
        }
        userNotifiedDisconnectRef.current = false;

        const retryHint =
          "Forge will retry automatically. If this keeps happening, ensure the API backend is running, then refresh this page.";

        disconnectToastTimerRef.current = setTimeout(() => {
          disconnectToastTimerRef.current = null;
          userNotifiedDisconnectRef.current = true;
          if (reason === "io server disconnect") {
            toast.error("Disconnected by server", { description: retryHint });
          } else {
            toast.error("Connection lost", { description: retryHint });
          }
        }, SUSTAINED_DISCONNECT_NOTICE_MS);
      });

      socket.io.on("reconnect_attempt", () => {
        setReconnecting(true);
      });

      socket.io.on("reconnect", () => {
        setReconnecting(false);
        setConnected(true);

        if (disconnectToastTimerRef.current) {
          clearTimeout(disconnectToastTimerRef.current);
          disconnectToastTimerRef.current = null;
        }
        const showRecoveryToast = userNotifiedDisconnectRef.current;
        userNotifiedDisconnectRef.current = false;

        void (async () => {
          const convId = conversationIdRef.current;
          const afterId = useSessionStore.getState().latestEventId;
          if (convId) {
            try {
              const batch = await fetchConversationEventsAfter(convId, afterId);
              if (batch.length > 0) {
                mergeHistoricalEvents(batch);
                latestEventIdRef.current = useSessionStore.getState().latestEventId;
              }
            } catch (err) {
              console.warn("[forge] Reconnect REST catch-up failed", err);
            }
            useSessionStore.getState().pruneRecoverableTransientErrors();
            void queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
          }
          if (showRecoveryToast) {
            toast.success("Back online", {
              description: "Live updates and sending messages work again.",
            });
          }
        })();
      });

      socket.io.on("reconnect_failed", () => {
        setReconnecting(false);
        if (disconnectToastTimerRef.current) {
          clearTimeout(disconnectToastTimerRef.current);
          disconnectToastTimerRef.current = null;
        }
        userNotifiedDisconnectRef.current = false;
        toast.error("Could not reconnect", {
          description:
            "Check your network and that the Forge backend is up. Refresh this page to try again.",
        });
      });

      return offForge;
    },
    [addEvent, setConnected, setReconnecting, mergeHistoricalEvents],
  );

  useEffect(() => {
    if (!conversationId || conversationId === "new") return;
    if (connectedRef.current) return;
    connectedRef.current = true;

    const previousConversationId = useSessionStore.getState().conversationId;
    setConversation(conversationId);
    if (previousConversationId !== conversationId) {
      useContextPanelStore.getState().resetPanel();
    }
    clearStreaming();

    let cancelled = false;
    let offForge: (() => void) | null = null;

    void (async () => {
      if (useSessionStore.getState().events.length === 0) {
        try {
          const batch = await fetchAllConversationEvents(conversationId);
          if (!cancelled && batch.length > 0) {
            mergeHistoricalEvents(batch);
          }
        } catch (err) {
          console.warn("[forge] Failed to hydrate events from API", err);
        }
      }

      if (cancelled) return;

      const replayAfterId = useSessionStore.getState().latestEventId;
      latestEventIdRef.current = replayAfterId;
      offForge = connect(conversationId, replayAfterId);
    })();

    return () => {
      cancelled = true;
      if (disconnectToastTimerRef.current) {
        clearTimeout(disconnectToastTimerRef.current);
        disconnectToastTimerRef.current = null;
      }
      userNotifiedDisconnectRef.current = false;
      offForge?.();
      disconnectSocket();
      connectedRef.current = false;
    };
  }, [conversationId, setConversation, connect, clearStreaming, mergeHistoricalEvents]);
}
