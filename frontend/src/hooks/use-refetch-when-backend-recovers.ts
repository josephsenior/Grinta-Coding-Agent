import { useEffect, useRef } from "react";
import { useBackendHealth } from "@/hooks/use-backend-health";
import { useSessionStore } from "@/stores/session-store";

/**
 * Calls `fetchFn` when connectivity likely recovered after a failure:
 * - Backend health goes from disconnected (false) to connected (true)
 * - Socket reconnects (false → true) for the chat session
 * - Window `online` (tab wake, Wi‑Fi back, etc.)
 *
 * When `onlyIfInErrorState` is true, skips unless `inErrorState` is true (avoids redundant fetches).
 */
export function useRefetchWhenBackendRecovers(
  fetchFn: () => void | Promise<void>,
  onlyIfInErrorState: boolean,
  inErrorState: boolean,
) {
  const prevConnected = useRef<boolean | null>(null);
  const prevSocket = useRef<boolean | null>(null);
  const { connected } = useBackendHealth();
  const socketConnected = useSessionStore((s) => s.isConnected);
  const fetchRef = useRef(fetchFn);
  fetchRef.current = fetchFn;
  const onlyErrorRef = useRef(onlyIfInErrorState);
  onlyErrorRef.current = onlyIfInErrorState;
  const inErrorRef = useRef(inErrorState);
  inErrorRef.current = inErrorState;

  const shouldRun = () => !onlyErrorRef.current || inErrorRef.current;

  useEffect(() => {
    if (connected !== true) {
      prevConnected.current = connected;
      return;
    }
    const wasDisconnected = prevConnected.current === false;
    prevConnected.current = true;
    if (wasDisconnected && shouldRun()) {
      void Promise.resolve(fetchRef.current());
    }
  }, [connected]);

  useEffect(() => {
    if (!socketConnected) {
      prevSocket.current = socketConnected;
      return;
    }
    const wasDisconnected = prevSocket.current === false;
    prevSocket.current = socketConnected;
    if (wasDisconnected && shouldRun()) {
      void Promise.resolve(fetchRef.current());
    }
  }, [socketConnected]);

  useEffect(() => {
    const onOnline = () => {
      if (shouldRun()) {
        void Promise.resolve(fetchRef.current());
      }
    };
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, []);
}
