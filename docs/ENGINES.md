# Grinta Agent Engines

Grinta ships with five specialized AI engines, each optimized for different
task types. The **Orchestrator** is the default and handles most coding tasks.

---

## Engine Overview

| Engine | Purpose | Best For |
|--------|---------|----------|
| **Orchestrator** | Full-featured autonomous coding agent | Coding, debugging, refactoring |
| **MCP Browser** | Remote web browsing via MCP | Web interaction, research |
| **Locator** | Code navigation via graph | Finding files, symbols, dependencies |
| **Auditor** | Code review engine | Code quality analysis |
| **Echo** | Test/debug echo | Testing, development |

---

## 1. Orchestrator

**Default engine.** The Orchestrator uses a ReAct (Reasoning + Acting) loop
to solve coding tasks through iterative observation and action cycles.

### How It Works

```
Think → Act → Observe → Repeat
```

1. **Observe** current project state
2. **Reason** about the next step
3. **Act** (edit file, run command, browse web via MCP)
4. **Observe** the result
5. **Repeat** until task is complete or budget exhausted

### Available Tools (23)

| Category | Tools |
|----------|-------|
| **File editing** | `str_replace_editor`, `llm_based_edit`, `atomic_refactor`, `whitespace_handler` |
| **Commands** | `bash` |
| **Browser** | `MCP Browser (browser-use)` |
| **Reasoning** | `think`, `finish`, `task_tracker`, `summarize_context` |
| **Code quality** | `smart_errors`, `health_check` |
| **Security** | `security_utils` |
| **Utilities** | `prompt`, `server_readiness_helper`, `database` |

### Key Components

- **Planner** (`planner.py`): Decomposes complex tasks into steps
- **Executor** (`executor.py`): Runs planned actions
- **Hallucination Detector** (`hallucination_detector.py`): Validates agent outputs
- **Anti-Hallucination System** (`anti_hallucination_system.py`): Proactive prevention
- **Safety** (`safety.py`): Action risk classification
- **Task Complexity** (`task_complexity.py`): Estimates task difficulty
- **Memory Manager** (`memory_manager.py`): Engine-level context management
- **File Verification Guard** (`file_verification_guard.py`): Validates file edits

### Configuration

```toml
[agent]
default_agent = "Orchestrator"
enable_editor = true
enable_cmd = true
enable_browsing = true
enable_think = true
enable_finish = true

```

### Prompt Templates

Located in `backend/engine/prompts/`. Jinja2 templates define
the system prompt, including role definition, available tools, output format,
best practices, and few-shot examples.

**See:** [backend/engine/README.md](../backend/engine/README.md)

---

## 2. MCP Browser (Remote Browsing)

Web browsing is decoupled from the core App engine via the Model Context
Protocol. This allows for flexible browsing engines like `browser-use` or
other MCP-compatible agents.

### How It Works

```
App → MCP Request → MCP Browser Server → Web Interaction → App
```

### Key Components

- **MCP Integration** (`mcp_integration/`): Universal protocol bridge
- **MCP Toolset**: Dynamically discovered tools like `navigate`, `click`, etc.

### When to Use

- Web research tasks
- Interacting with web applications
- Scraping structured data from websites
- Testing web interfaces

### Configuration

MCP tools are automatically discovered and enabled when the `enable_browsing`
flag is set and a corresponding MCP server is connected.

```toml
[agent]
enable_browsing = true
```

> **Note:** Remote browsing via MCP provides superior isolation and
> flexibility compared to in-process browser automation.

---

## 3. Locator (Code Navigation)

The Locator implements graph-based code navigation using the
[Locagent](https://arxiv.org/abs/2503.09089) framework. It parses codebases
into directed heterogeneous graphs capturing code structures and dependencies.

### How It Works

```
Parse Codebase → Build Graph → LLM Multi-Hop Reasoning → Locate Target
```

### Built-in Tools

| Tool | Purpose |
|------|---------|
| `search_code_snippets` | Search for code patterns |
| `read_symbol_definition` | Retrieve entity source code |
| `explore_tree_structure` | Navigate code hierarchy |

### Key Components

- **Locator** (`locator.py`): Main localization engine
- **Graph Cache** (`graph_cache.py`): Cached code graph representation
- **Function Calling** (`function_calling.py`): LLM tool interface

### When to Use

- Finding specific functions, classes, or symbols
- Understanding dependency chains
- Navigating unfamiliar codebases
- Locating bugs in large projects

---

## 4. Auditor (Code Review)

The Auditor engine performs code review by analyzing code quality, identifying
issues, and suggesting improvements.

### Key Components

- **Auditor** (`auditor.py`): Main review engine
- **Function Calling** (`function_calling.py`): LLM tool interface
- **Tools**: File cache, glob, grep, semantic search, explorer, view

### Built-in Tools

| Tool | Purpose |
|------|---------|
| `file_cache` | Cache and retrieve file contents |
| `glob` | Pattern-based file discovery |
| `grep` | Content search across files |
| `semantic_search` | Semantic code search |
| `explore_structure` | Navigate project structure |
| `view` | View file contents |

### When to Use

- Code review automation
- Quality analysis
- Finding potential issues across a codebase

---

## 5. Echo (Debug)

A minimal echo engine used for testing and development. It echoes back
inputs with minimal processing.

### When to Use

- Testing the agent pipeline
- Debugging event flow
- Development and integration testing

---

## Engine Selection

By default, the Orchestrator handles all tasks. To use a specific engine:

```toml
[core]
default_agent = "Orchestrator"   # or "Navigator", "Locator", etc.
```

Or configure named agents with specific engines:

```toml
[agent.CodeReviewAgent]
classpath = "backend.engine.auditor.auditor.AuditorAgent"
llm_config = "fast"
```

## Adding Custom Engines

1. Create the implementation under `backend/engine/` or an adjacent package
2. Implement the agent interface (see `backend/tests/support/echo/` for a minimal example)
3. Register via `classpath` in agent config

```toml
[agent.MyCustomAgent]
classpath = "my_package.my_module.MyAgent"
```
