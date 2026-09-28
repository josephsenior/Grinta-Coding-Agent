# Inference and Integrations

This guide maps how Grinta talks to **LLM providers** versus **external tools**. For package topology, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Three tiers

| Tier | Role | Location |
|------|------|----------|
| **Inference providers** | Route models, call LLM APIs, normalize tool calls | [`backend/inference/`](../backend/inference/) |
| **Native agent tools** | Core coding: read, edit, bash, grep, browser, LSP | [`backend/engine/tools/`](../backend/engine/tools/) + [`backend/execution/`](../backend/execution/) |
| **MCP extensions** | Curated external capabilities (GitHub, Exa, Context7, …) | [`backend/integrations/mcp/`](../backend/integrations/mcp/) |

## Inference layer

**Registry and provider resolution:** [`backend/inference/llm_registry.py`](../backend/inference/llm_registry.py) and [`backend/inference/provider_resolver.py`](../backend/inference/provider_resolver.py)

Responsibilities:

- Provider IDs, default base URLs, and model listing (static catalog + optional remote `/v1/models` + local discovery)
- LLM transport via [`llm/`](../backend/inference/llm/) and provider clients in [`clients/`](../backend/inference/clients/)
- Capability lookup (catalog → conservative defaults for uncataloged ids)

Configuration keys and param validation live in [`backend/core/config/`](../backend/core/config/). Prompt assembly lives in [`backend/engine/prompts/`](../backend/engine/prompts/) and [`backend/context/`](../backend/context/) — those consume inference; they do not call providers directly.

### Tsubasa through the OpenAI-compatible client

Merge these values into `settings.json` and set `LLM_API_KEY` in your environment
or local `.env` file:

```json
{
  "llm_provider": "openai",
  "llm_model": "tsubasa-fast",
  "llm_base_url": "https://api.tsubasa.sh/v1",
  "llm_api_key": "${LLM_API_KEY}",
  "llm_context_window_tokens": 32768,
  "llm_max_output_tokens": 4096
}
```

Use `tsubasa-pro` for the other alias; the same limits above apply. The output
setting reserves part of the 32,768-token context window, so prompts, tool
definitions and conversation history must fit alongside it. This configuration
sends prompts and the configured key to `api.tsubasa.sh`. Grinta's agent requires
tool calls to be enabled for the selected endpoint and model; configuring a
custom alias does not enable that capability. See [SETTINGS.md](SETTINGS.md) for
configuration locations and precedence.

### Model listing sources

Grinta uses **catalog-only listing** for hosted providers and **live probes** for local runtimes:

1. **Static catalog (hosted providers)** — [`catalogs/*.json`](../backend/inference/catalogs/) are the single source of truth for picker models, pricing, limits, capability flags, reasoning tiers/wires, param overrides, and aliases.
2. **Local probe (Ollama / LM Studio / vLLM)** — [`provider_catalog.get_local_model_names()`](../backend/inference/catalog/provider_catalog.py) delegates discovery to the provider resolver when the local server is running.
3. **Conservative fallback** — uncataloged manual/local model ids use safe defaults via [`param_profiles.py`](../backend/inference/capabilities/param_profiles.py).
4. **Session pinning** — [`runtime_profile.py`](../backend/inference/runtime_profile.py) pins limits on the LLM instance; `settings.json` overrides still win.

### Catalog maintenance

When a hosted provider ships a model you want in pickers or docs:

1. Add a row under the provider file in [`catalogs/*.json`](../backend/inference/catalogs/) with a full `runtime` block:
   - limits, pricing, tool flags (`supports_*`)
   - param overrides (`strip_temperature`, `use_max_completion_tokens`, …)
   - reasoning config (`reasoning_efforts`, `reasoning_wire`) when the model supports thinking/reasoning
   - optional `metadata.variants` for rich per-tier API payloads (OpenCode routes)
2. Set `verified: true` / `featured: true` for demo-ready models.
3. Run `pytest backend/tests/unit/inference/test_catalog_integrity.py` — validates JSON schema, alias resolution, picker listing, and transport invariants for every catalog row.

Batch updates on flagship releases; do not mirror every provider API rename automatically.

## Integrations layer

[`backend/integrations/`](../backend/integrations/) contains **MCP only**. Other “integrations” are intentionally native:

| Capability | Why not MCP | Where |
|------------|-------------|-------|
| Browser | Latency-sensitive, vision loop | [`execution/browser/`](../backend/execution/browser/) |
| LSP / debugger | Tight runtime coupling | [`engine/tools/`](../backend/engine/tools/) + [`execution/dap/`](../backend/execution/dap/) |
| Web search / fetch | Stable LLM-facing facade over Exa MCP | [`engine/tools/web_tools.py`](../backend/engine/tools/web_tools.py) |
| Ops HTTP (logs, alerts) | Not agent tools | [`core/external_service.py`](../backend/core/external_service.py) |

MCP tools are **gatewayed** through `call_mcp_tool` (see [journey/43](journey/43-the-plugin-boundary.md)) so the LLM tool list stays compact.

## Naming note

[`backend/execution/utils/tool_registry.py`](../backend/execution/utils/tool_registry.py) detects **host OS binaries** (git, bash, ripgrep). It is unrelated to [`backend/engine/tool_registry.py`](../backend/engine/tool_registry.py), which validates LLM tool names.
