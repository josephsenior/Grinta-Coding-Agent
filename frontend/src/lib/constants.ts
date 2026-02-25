export const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:3000";
// Direct backend URL for socket.io. Override with VITE_WS_URL to point at a remote backend.
// In development, this means the browser connects directly to :3000 (backend allows all origins).
// In production the frontend is served from :3000 so this is same-origin.
export const WS_URL = import.meta.env.VITE_WS_URL || "http://localhost:3000";
export const API_PREFIX = "/api/v1";
