export const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:3000";
// Direct backend URL for socket.io. Override with VITE_WS_URL to point at a remote backend.
// In development, this means the browser connects directly to :3000 (backend allows all origins).
// In production the frontend is served from :3000 so this is same-origin.
export const WS_URL = import.meta.env.VITE_WS_URL || "http://localhost:3000";
export const API_PREFIX = "/api/v1";

/** Min ms disconnected before sustained-offline UI (disconnect toast + Chat red banner). Brief blips stay clean. */
export const SUSTAINED_DISCONNECT_NOTICE_MS = 2000;

/**
 * While the agent is RUNNING, show "No response for a while…" after this many ms without new events/streaming.
 * Default 0 = disabled. Set VITE_AGENT_RUNNING_STALE_UI_MS in .env to enable (e.g. 90000 for 90s).
 */
function parseAgentRunningStaleUiMs(): number {
  const raw = import.meta.env.VITE_AGENT_RUNNING_STALE_UI_MS;
  if (raw === "" || raw === undefined) return 0;
  const n = Number(raw);
  if (!Number.isFinite(n)) return 0;
  return n;
}

export const AGENT_RUNNING_STALE_UI_MS = parseAgentRunningStaleUiMs();
