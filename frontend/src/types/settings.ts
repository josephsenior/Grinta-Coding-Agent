export interface MCPServerConfig {
  name: string;
  type: "stdio" | "sse" | "shttp";
  command?: string | null;
  args?: string[];
  env?: Record<string, string>;
  url?: string | null;
  api_key?: string | null;
  transport?: "sse" | "shttp";
  /** One-line hint injected into the agent system prompt (when to use this server). */
  usage_hint?: string | null;
}

export interface MCPConfig {
  servers: MCPServerConfig[];
}

export interface StartupSnapshot {
  host?: string;
  requested_port?: number;
  resolved_port?: number;
  port_auto_switched?: boolean;
  reload_enabled?: boolean;
  runtime?: string;
  project_root?: string;
  cwd?: string;
  app_root?: string;
  settings_path?: string;
  dotenv_local_loaded?: boolean;
  agent_config_present?: boolean;
  ui_url?: string;
  api_url?: string;
  docs_url?: string;
  health_url?: string;
  recorded_at?: number;
  [key: string]: unknown;
}

export interface RecoveryRestoreRecord {
  sid?: string;
  source?: string;
  path?: string;
  primary_error?: string | null;
  recorded_at?: number;
  [key: string]: unknown;
}

export interface RecoverySnapshot {
  status?: string;
  detail?: string;
  state_restores?: {
    count?: number;
    recent?: RecoveryRestoreRecord[];
  };
  event_streams?: {
    streams?: number;
    persist_failures?: number;
    durable_writer_errors?: number;
    critical_events?: number;
    critical_sync_persistence?: number;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface SettingsResponse {
  llm_model?: string | null;
  llm_provider?: string | null;
  llm_api_key?: null; // always masked
  llm_api_key_set?: boolean;
  llm_base_url?: string | null;
  llm_temperature?: number | null;
  llm_top_p?: number | null;
  llm_max_output_tokens?: number | null;
  /** From server catalog — whether the selected llm_model supports image inputs. */
  llm_model_supports_vision?: boolean;
  mcp_config?: MCPConfig | null;
  startup_snapshot?: StartupSnapshot | null;
  recovery_snapshot?: RecoverySnapshot | null;
  [key: string]: unknown;
}

export interface SecretStatus {
  name: string;
  is_set: boolean;
}
