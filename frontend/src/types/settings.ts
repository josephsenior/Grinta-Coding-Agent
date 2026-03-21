export interface MCPServerConfig {
  name: string;
  type: "stdio" | "sse" | "shttp";
  command?: string | null;
  args?: string[];
  env?: Record<string, string>;
  url?: string | null;
  api_key?: string | null;
  transport?: "sse" | "shttp";
}

export interface MCPConfig {
  servers: MCPServerConfig[];
}

export interface SettingsResponse {
  llm_model?: string | null;
  llm_api_key?: null; // always masked
  llm_api_key_set?: boolean;
  llm_base_url?: string | null;
  llm_temperature?: number | null;
  llm_top_p?: number | null;
  llm_max_output_tokens?: number | null;
  /** From server catalog — whether the selected llm_model supports image inputs. */
  llm_model_supports_vision?: boolean;
  mcp_config?: MCPConfig | null;
  [key: string]: unknown;
}

export interface SecretStatus {
  name: string;
  is_set: boolean;
}
