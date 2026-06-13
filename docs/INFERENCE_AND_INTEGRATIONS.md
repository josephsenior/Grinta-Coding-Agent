# Inference and Integrations

This guide maps how Grinta talks to **LLM providers** versus **external tools**. For package topology, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Three tiers

| Tier | Role | Location |
|------|------|----------|
| **Inference providers** | Route models, call LLM APIs, normalize tool calls | [`backend/inference/`](../backend/inference/) |
| **Native agent tools** | Core coding: read, edit, bash, grep, browser, LSP | [`backend/engine/tools/`](../backend/engine/tools/) + [`backend/execution/`](../backend/execution/) |
| **MCP extensions** | Curated external capabilities (GitHub, Exa, Context7, …) | [`backend/integrations/mcp/`](../backend/integrations/mcp/) |

## Inference layer

**Public read API:** [`backend/inference/registry.py`](../backend/inference/registry.py)

Responsibilities:

- Provider IDs, default base URLs, and model listing (static catalog + optional remote `/v1/models` + local discovery)
- LLM transport via [`llm.py`](../backend/inference/llm.py) and [`direct_clients.py`](../backend/inference/direct_clients.py)
- Capability lookup (catalog → model glob patterns → provider defaults)

Configuration keys and param validation live in [`backend/core/config/`](../backend/core/config/). Prompt assembly lives in [`backend/engine/prompts/`](../backend/engine/prompts/) and [`backend/context/`](../backend/context/) — those consume inference; they do not call providers directly.

### Model listing sources

1. **Unified dynamic listing** — [`registry.list_models()`](backend/inference/registry.py) via transport adapters in [`model_list_backends.py`](backend/inference/model_list_backends.py) (OpenAI `/v1/models`, Anthropic models API, Google `genai`, local probes)
2. **Featured catalog stubs** — offline defaults and pricing only ([`catalogs/*.json`](backend/inference/catalogs/))
3. **Param profiles** — family-level call-surface rules in [`param_profiles.json`](backend/inference/param_profiles.json); provider defaults for Tier 2/3
4. **Session pinning** — [`runtime_profile.py`](backend/inference/runtime_profile.py) pins limits on the LLM instance; `settings.json` overrides still win

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
