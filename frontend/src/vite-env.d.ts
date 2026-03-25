/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  readonly VITE_WS_URL: string;
  /** Milliseconds before "No response for a while" while agent is running; "0" disables. */
  readonly VITE_AGENT_RUNNING_STALE_UI_MS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
