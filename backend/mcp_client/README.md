# MCP Utilities

This directory contains the Model Context Protocol (MCP) integration utilities for Forge.

## Components

- `client.py` – Lightweight asynchronous client wrapper that discovers and calls remote MCP tools over SSE, SHTTP, or stdio transports.
- `utils.py` – High-level orchestration helpers for connecting servers, exposing tools to agents, and dispatching tool calls.
- `tool.py` – `MCPClientTool` metadata wrapper to expose each remote tool as an OpenAI style function parameter.
- `error_collector.py` – Aggregates connection and invocation errors for diagnostics.
- `cache.py` – In‑process time‑based cache for deterministic MCP tool results.
- `wrappers.py` – Synthetic wrapper tools layered above server tools that provide higher-level or cached functionality.

## Caching Layer

`cache.py` implements a minimal per‑process cache:

- Eligible tools (deterministic, frequently reused): `list_components`, `list_blocks`, `get_component`, `get_block`, `get_component_metadata`.
- Key format: `<tool_name>::<stable_sorted_args_json>` (control flags `refresh` & `no_cache` are excluded from the key).
- TTL: 600s (10 minutes) by default; large entries (>5MB serialized by default) are skipped.
- Max per-entry size is configurable via env var `FORGE_MCP_CACHE_MAX_ENTRY_BYTES` (bytes).
- Errors (payloads including `isError: true`) are not cached.
- Bypass controls: pass `{"refresh": true}` or `{"no_cache": true}` in tool arguments.
- Helper API: `get_cached`, `set_cache`, `clear_cache(prefix?)`.

The cache is integrated inside `call_tool_mcp` (and `_call_mcp_raw` for wrapper reuse). A cache hit short‑circuits an MCP transport round trip and returns the previously serialized `CallToolResult` payload.

## Wrapper Tools

Added automatically when underlying primitives are discovered:

| Wrapper Tool           | Depends On        | Purpose                                                                        |
| ---------------------- | ----------------- | ------------------------------------------------------------------------------ |
| `search_components`    | `list_components` | Fuzzy / substring filtering client-side on cached list to reduce remote calls. |
| `get_component_cached` | `get_component`   | Adds caching + explicit `refresh` semantics.                                   |
| `get_block_cached`     | `get_block`       | Same pattern for blocks.                                                       |

### `search_components` Parameters

- `query` (required): search string.
- `limit` (default 10): maximum results.
- `fuzzy` (default true): enables subsequence fuzzy scoring; when false uses simple substring matching.

### Refresh Semantics

All cached wrappers honor `refresh=true` to bypass cache. For underlying raw tools, the same flag works if the agent calls them directly.

## Agent Guidance (Prompt Hint)

System prompt additions should encourage:

1. Use `search_components` to narrow candidates.
2. Fetch details with `get_component_cached` / `get_block_cached`.
3. Use `refresh=true` if you suspect upstream changes (e.g., after adding a new component externally).

## Extending

To add a new cached tool:

1. Add its name to `_CACHEABLE_TOOLS` in `cache.py`.
2. Ensure result is deterministic & reasonably sized.
3. (Optional) Provide a wrapper if additional filtering/aggregation is useful.

## Limitations / Future Ideas

- No persistence across process restarts.
- No stale-while-revalidate; could serve stale results while asynchronously refreshing.
- No metrics exported; adding simple counters for hit/miss could help tuning TTL.
- No LRU trimming: with few deterministic endpoints this is acceptable.

## Maintenance

If a server tool schema changes, wrappers will still pass through arguments transparently (except for added control flags). Review wrapper logic (`search_components`) if the list payload structure changes (currently expects the first text segment to be a JSON array of names).
