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

Grinta uses **catalog-first listing** with optional remote merge and live local probes:

1. **Static catalog (default for hosted providers)** — [`catalogs/*.json`](backend/inference/catalogs/) define curated models with pricing, limits, param overrides, and aliases. Pickers load these by default.
2. **Optional remote merge** — set `GRINTA_INCLUDE_REMOTE_MODEL_LISTING=1` or pass `include_remote=True` to [`registry.build_model_entries_by_provider()`](backend/inference/registry.py) / [`list_model_names()`](backend/inference/registry.py) to append ids from provider `/v1/models` APIs via [`model_list_backends.py`](backend/inference/model_list_backends.py).
3. **Local probe (always for Ollama / LM Studio / vLLM)** — live discovery when the local server is running; catalog rows are optional fallback.
4. **Param profiles** — family-level call-surface rules in [`param_profiles.json`](backend/inference/param_profiles.json); applied when a catalog row is missing (manual model ids, local models).
5. **Session pinning** — [`runtime_profile.py`](backend/inference/runtime_profile.py) pins limits on the LLM instance; `settings.json` overrides still win.

### Catalog maintenance

When a hosted provider ships a model you want in pickers or docs:

1. Add a row under the provider file in [`catalogs/*.json`](backend/inference/catalogs/) with a full `runtime` block (limits, tool flags, thinking/reasoning overrides).
2. Set `verified: true` / `featured: true` for demo-ready models.
3. Extend [`reasoning_profiles.json`](backend/inference/reasoning_profiles.json) only when the model introduces a **new family** of reasoning tiers.
4. Extend [`param_profiles.json`](backend/inference/param_profiles.json) only for models without a catalog row (local ids, manual entry).
5. Run `pytest backend/tests/unit/inference/test_catalog_integrity.py`.

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
