import { useEffect, useRef, useCallback } from "react";
import { useSessionStore } from "@/stores/session-store";
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
        // Dedup: skip events we already have (can happen during replay after reconnection)
        if (event.id <= latestEventIdRef.current) return;
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
    const unsubscribe = connect(conversationId, -1);

    return () => {
      unsubscribe();
      disconnectSocket();
      connectedRef.current = false;
    };
  }, [conversationId, setConversation, connect]);
}
