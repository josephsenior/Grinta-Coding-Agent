# Grinta Agent Engines

Grinta's current tree is centered on **one production agent engine** and **one minimal test-support agent**.

The production system is the **Orchestrator**. Web browsing and other remote capabilities are exposed through tools and MCP integration, not through separate built-in agent engines. The `Echo` agent exists as a deterministic harness for tests and custom-agent examples.

This document reflects the engines that are actually present in the current repository.

---

## Engine Overview

| Engine / Capability | Status | Best For |
| --- | --- | --- |
| **Orchestrator** | Production engine | Coding, debugging, refactoring, multi-step task execution |
| **MCP-powered browsing** | Capability used by the Orchestrator | Web research, browser automation, remote tools |
| **Echo** | Test-support agent | Deterministic testing, pipeline debugging, custom-agent examples |

---

## 1. Orchestrator

**Default engine.** The Orchestrator is the main agent loop Grinta ships today.

It coordinates planning, tool use, observation handling, safety checks, memory, and finish behavior. If you are using Grinta normally, this is the engine doing the work.

### Execution Loop

At a high level, the Orchestrator runs a deliberate loop:

```text
Observe -> Plan -> Act -> Observe -> Validate -> Repeat
```

The exact runtime path depends on the task and enabled tools, but the important point is that the Orchestrator is not just a chat wrapper. It is the control loop around the model.

### Core Modules

These are the main implementation files in `backend/engine/` today:

- `orchestrator.py`: top-level agent orchestration
- `planner.py`: plan construction and task decomposition
- `executor.py`: action execution and result handling
- `safety.py`: risk classification and action policy support
- `memory_manager.py`: working-memory and retrieval coordination
- `reflection.py`: optional reflection flow
- `action_verifier.py`: post-action verification helpers
- `streaming_checkpoint.py`: checkpointing and recovery support
- `tool_registry.py`: tool registration and availability
- `function_calling.py`: tool-call parsing and model I/O glue

### Common Tool Surface

The exact tool list is **configuration-dependent**. A typical Orchestrator session exposes a mix of:

- reasoning and control tools: `think`, `finish`, `task_tracker`
- project exploration tools: `search_code`, `analyze_project_structure`, `explore_tree_structure`, `read_symbol_definition`
- editing tools: `str_replace_editor`, `structure_editor`, `apply_patch`
- execution tools: `bash`, `terminal_manager`
- memory tools: `memory_manager`, `note`, `recall`
- external capability bridge: `call_mcp_tool`

Some tools appear only when specific features are enabled, so it is better to think of the Orchestrator as a configurable engine with a stable core rather than a fixed tool count.

### Prompt System

Prompt assembly lives in `backend/engine/prompts/` and is now built through a **pure-Python prompt builder** with markdown partials, not Jinja2 templates.

See:

- `backend/engine/prompts/prompt_builder.py`
- `backend/engine/README.md`
- [journey/15-prompts-are-programs.md](journey/15-prompts-are-programs.md)

---

## 2. MCP-Powered Browsing and Remote Capabilities

Browsing is a capability, not a separate built-in agent class in the main engine tree.

The Orchestrator reaches external capabilities through the Model Context Protocol layer in `backend/integrations/mcp/`. That includes browser automation when the appropriate MCP server is configured, but it also includes any other external tool the MCP gateway exposes.

### How It Works

```text
Orchestrator -> call_mcp_tool(...) -> MCP integration layer -> connected server -> result back to agent
```

### When to Use

- web research
- browser interaction
- remote tool integration
- capabilities that do not belong in the native local tool layer

### Important Clarification

Earlier drafts of this documentation treated "MCP Browser" like a standalone first-class engine. In the current codebase, it is more accurate to describe browsing as a capability surfaced through MCP, not a separate production agent peer to the Orchestrator.

---

## 3. Echo

`Echo` is a minimal deterministic agent used in test support.

It lives under:

- `backend/tests/support/echo/agent.py`

### What It Does

The Echo agent is not meant to be a user-facing coding engine. It exists to exercise the agent pipeline predictably by emitting predefined actions and observations.

That makes it useful for:

- testing event flow
- validating agent/runtime plumbing
- debugging integration behavior without a real model in the loop
- serving as the smallest useful custom-agent example

If you want to understand the minimum amount of code required to plug a custom agent into the system, Echo is the right starting point.

---

## Engine Selection and Custom Agents

The default agent name in the current codebase is `Orchestrator`.

Custom agents can be registered through the config loader with a `classpath` entry. The app config stores a dictionary of named agents plus the `default_agent` name that should be used by default.

Example pattern:

```toml
default_agent = "MyCustomAgent"

[agent.MyCustomAgent]
classpath = "my_package.my_module.MyAgent"
```

See:

- `backend/core/config/app_config.py`
- `backend/core/config/config_loader.py`

---

## What Is Not Bundled Today

The current Grinta tree does **not** ship separate built-in `Locator` or `Auditor` engines.

If you want specialized code-navigation or review agents, the right model is to implement them as custom agents and register them through the same `classpath` mechanism used elsewhere in the config system.

That keeps this document aligned with the code that actually exists rather than preserving older architectural sketches as if they were shipping product.
