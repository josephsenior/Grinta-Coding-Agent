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
- Capability lookup (catalog → conservative defaults for uncataloged ids)

Configuration keys and param validation live in [`backend/core/config/`](../backend/core/config/). Prompt assembly lives in [`backend/engine/prompts/`](../backend/engine/prompts/) and [`backend/context/`](../backend/context/) — those consume inference; they do not call providers directly.

### Model listing sources

Grinta uses **catalog-only listing** for hosted providers and **live probes** for local runtimes:

1. **Static catalog (hosted providers)** — [`catalogs/*.json`](../backend/inference/catalogs/) are the single source of truth for picker models, pricing, limits, capability flags, reasoning tiers/wires, param overrides, and aliases.
2. **Local probe (Ollama / LM Studio / vLLM)** — [`registry.get_local_model_names()`](../backend/inference/registry.py) discovers installed models when the local server is running.
3. **Conservative fallback** — uncataloged manual/local model ids use safe defaults (tools on, reasoning off) via [`param_profiles.py`](../backend/inference/param_profiles.py).
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
