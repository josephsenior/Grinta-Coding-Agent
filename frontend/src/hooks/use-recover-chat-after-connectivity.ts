import { useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useBackendHealth } from "@/hooks/use-backend-health";
import { useSessionStore } from "@/stores/session-store";

/**
 * Clears stale transient error cards from the timeline and refetches conversation metadata
 * when the API is reachable again (matches workspace FilesTree/GitChanges recovery behavior).
 */
export function useRecoverChatAfterConnectivity(conversationId: string | undefined) {
  const queryClient = useQueryClient();
  const prevHealth = useRef<boolean | null>(null);
  const { connected } = useBackendHealth();

  const recover = useCallback(() => {
    useSessionStore.getState().pruneRecoverableTransientErrors();
    if (conversationId) {
      void queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
    }
  }, [conversationId, queryClient]);

  useEffect(() => {
    if (connected !== true) {
      prevHealth.current = connected;
      return;
    }
    const wasDisconnected = prevHealth.current === false;
    prevHealth.current = true;
    if (wasDisconnected) recover();
  }, [connected, recover]);

  useEffect(() => {
    window.addEventListener("online", recover);
    return () => window.removeEventListener("online", recover);
  }, [recover]);
}
