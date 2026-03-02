import { useEffect, useRef, useCallback } from "react";
import { useSessionStore } from "@/stores/session-store";
import { useContextPanelStore } from "@/stores/context-panel-store";
import { connectSocket, disconnectSocket, onForgeEvent } from "@/socket/client";
import { toast } from "sonner";

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
  } = useSessionStore();

  // Keep latestEventId in a ref so reconnection always uses current value
  const latestEventIdRef = useRef(latestEventId);
  latestEventIdRef.current = latestEventId;

  // Track whether this is the initial mount to avoid double-connect in StrictMode
  const connectedRef = useRef(false);

  const connect = useCallback(
    (convId: string, fromEventId: number) => {
      const socket = connectSocket({
        conversationId: convId,
        latestEventId: fromEventId,
      });

      socket.on("connect", () => {
        setConnected(true);
        setReconnecting(false);
      });

      socket.on("disconnect", (reason) => {
        setConnected(false);
        if (reason === "io server disconnect") {
          toast.error("Disconnected by server");
        }
      });

      socket.io.on("reconnect_attempt", () => {
        setReconnecting(true);
      });

      socket.io.on("reconnect", () => {
        setReconnecting(false);
        setConnected(true);
        toast.success("Reconnected");
      });

      socket.io.on("reconnect_failed", () => {
        setReconnecting(false);
        toast.error("Failed to reconnect");
      });

      const unsubscribe = onForgeEvent((event) => {
        if (typeof event.id === "number" && event.id >= 0) {
          // Skip exact duplicates (replay after reconnection).
          if (event.id <= latestEventIdRef.current) return;

          // Detect replay gaps: if event ID jumps by more than a small
          // tolerance, the server may have pruned intermediate events.
          const gap = event.id - latestEventIdRef.current;
          if (latestEventIdRef.current >= 0 && gap > 50) {
            console.warn(
              `[forge] Event gap detected: expected ~${latestEventIdRef.current + 1}, got ${event.id} (gap=${gap}). Some history may be missing.`,
            );
          }

          // Update ref immediately — don't wait for React re-render — to
          // block duplicate events that arrive before the next render cycle.
          latestEventIdRef.current = event.id;
        }
        addEvent(event);
      });

      return unsubscribe;
    },
    [addEvent, setConnected, setReconnecting],
  );

  useEffect(() => {
    if (!conversationId) return;
    if (connectedRef.current) return;
    connectedRef.current = true;

    setConversation(conversationId);
    useContextPanelStore.getState().resetPanel();
    const unsubscribe = connect(conversationId, -1);

    return () => {
      unsubscribe();
      disconnectSocket();
      connectedRef.current = false;
    };
  }, [conversationId, setConversation, connect]);
}
