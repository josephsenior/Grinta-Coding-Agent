# Forge User Guide

> End-to-end guide: from installation to your first autonomous coding session.

## Table of Contents

1. [Installation](#installation)
2. [Configuration](#configuration)
3. [Your First Session](#your-first-session)
4. [Working with the Web UI](#working-with-the-web-ui)
5. [Working with the API](#working-with-the-api)
6. [LLM Providers](#llm-providers)
7. [Memory & Condensers](#memory--condensers)
8. [Safety & Budget Controls](#safety--budget-controls)
9. [MCP Integration](#mcp-integration)
10. [Playbooks](#playbooks)
11. [Advanced Configuration](#advanced-configuration)
12. [Performance Tuning](#performance-tuning)

---

## Installation

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.12+ | [python.org](https://python.org) |
| uv | 1.7+ | [docs.astral.sh/uv](https://docs.astral.sh/uv/) |
| Git | 2.30+ | [git-scm.com](https://git-scm.com/downloads) |

### Step 1: Clone and Install

```bash
git clone https://github.com/josephsenior/Forge.git
cd Forge
uv sync
```

### Step 2: Configure

```bash
echo "LLM_API_KEY=sk-your-api-key-here" > .env
```

Your API keys must be set via `.env` files ensuring all subprocesses inherit credentials properly. Use the Web UI to tune the rest of your agent parameters like Models and limits!

### Step 3: Start

**Windows (recommended):**

```powershell
.\START_HERE.ps1
```

**Manual start (any OS):**

Terminal 1 — Backend:

```bash
python start_server.py
```

Open the web UI at **http://localhost:3000** (or run `python forge.py` to start the server and open a browser tab automatically).

---

## Configuration

Forge uses a multi-layered configuration system based on JSON and Environment Variables to ensure flexibility across different environments and prevent UI syncing ambiguity.

### Configuration Hierarchy

Configuration loads with this exact precedence (highest wins):

1. **Environment Variables**: Native shell vars, `.env.local`, and `.env` (best for API keys)
2. **`settings.json` at the Forge app root**: The single source of truth for persisted settings (same file the Web UI reads and writes). Resolved via `FORGE_APP_ROOT` if set, otherwise the directory the backend process was started from — **not** the “Open folder” workspace path.
3. **Pydantic defaults**: Internal safe fallbacks.

If the UI and CLI disagree, confirm the backend’s working directory (or set `FORGE_APP_ROOT` to your Forge checkout) so everyone targets the same `settings.json`.

### Getting Started

For standard use, rely on the Web UI to edit the repo’s `settings.json` (under the app root above). Protect API keys in `.env` at the Forge project root (or via your shell environment):

```bash
LLM_API_KEY=sk-your-key
BROWSER_USE_API_KEY=bu_your-key
GITHUB_PERSONAL_ACCESS_TOKEN=github_pat_xxx
```

This ensures MCP processes (like `browser-use` or `github`) securely inherit credentials injected via `os.environ` upon backend startup.

### Advanced Settings (`settings.json`)

```json
{
  "llm_model": "gemini-pro-latest",
  "llm_temperature": 0.0,
  "max_budget_per_task": 5.0,
  "max_iterations": 500,
  "enable_browsing": true,
  "enable_circuit_breaker": true
}
```

### Environment Variables

Any setting can be injected. For complex setups, rely on `.env`:

| Config Path | Environment Variable |
|-------------|---------------------|
| `llm.api_key` | `LLM_API_KEY` |
| `llm.model` | `LLM_MODEL` |
| `core.max_budget_per_task` | `CORE_MAX_BUDGET_PER_TASK` |
| `agent.enable_browsing` | `AGENT_ENABLE_BROWSING` |

---

## Your First Session

### 1. Start Forge

```bash
python start_server.py
```

Then open **http://localhost:3000** in a browser.

### 2. Create a Conversation

From the web UI home screen, start a **new conversation** (or resume an existing one).

### 3. Describe Your Task

Type a natural language instruction:

```
Create a Python function that reads a CSV file, calculates the average
of a numeric column, and writes the result to a new file. Include error
handling and type hints.
```

### 4. Watch the Agent Work

The agent will:

1. **Think** about the approach
2. **Create** the file with your function
3. **Test** it by running the code
4. **Fix** any errors automatically
5. **Report** completion

### 5. Review Changes

The agent shows each action as it executes. You can:

- **Review diffs** in the diff viewer (press `d`)
- **Approve/reject** actions in confirmation mode
- **Interrupt** the agent at any time

### Example Tasks

| Task | Typical Cost | Iterations |
|------|-------------|------------|
| Fix a specific bug | $0.03–0.10 | 2–5 |
| Implement a function | $0.05–0.20 | 3–8 |
| Add tests for a module | $0.10–0.30 | 5–15 |
| Refactor a class | $0.15–0.50 | 8–20 |
| Build a feature end-to-end | $0.30–1.00 | 10–30 |

---

## Working with the Web UI

The primary interface is the React app served with the backend (default **http://localhost:3000**).
Use it to manage conversations, settings, confirmations, and workspace changes. The same REST and
Socket.IO APIs power automation via the Python package `forge_client` (see tests under
`backend/tests/unit/forge_client/` and `scripts/test_agent_via_sockets.py`).

---

## Working with the API

Forge exposes a REST + Socket.IO API on port 3000.

### REST Endpoints

```bash
# List conversations
curl http://localhost:3000/api/conversations

# Create conversation
curl -X POST http://localhost:3000/api/conversations \
  -H "Content-Type: application/json" \
  -d '{"task": "Fix the bug in main.py"}'

# Get conversation events
curl http://localhost:3000/api/conversations/{id}/events
```

### Socket.IO (Real-Time)

```python
import socketio

sio = socketio.Client()
sio.connect("http://localhost:3000")

@sio.on("agent_action")
def on_action(data):
    print(f"Agent action: {data}")

@sio.on("agent_observation")
def on_observation(data):
    print(f"Result: {data}")
```

### API Documentation

Interactive API docs are available at `http://localhost:3000/docs` when
the server is running.

---

## LLM Providers

### Supported Providers

| Provider | Models | Config |
|----------|--------|--------|
| **Anthropic** | Claude Sonnet 4, Claude Haiku | `model = "claude-sonnet-4-20250514"` |
| **OpenAI** | GPT-4o, GPT-4o-mini, o1 | `model = "gpt-4o"` |
| **Google** | Gemini 2.5 Pro, Flash | `model = "gemini/gemini-2.5-pro"` |
| **Ollama** | Any local model | `model = "ollama/llama3.2"` |

### Anthropic (Default)

```toml
[llm]
api_key = "sk-ant-..."
model = "claude-sonnet-4-20250514"
```

### OpenAI

```toml
[llm]
api_key = "sk-..."
model = "gpt-4o"
```

### Google Gemini

```toml
[llm]
api_key = "AIza..."
model = "gemini/gemini-2.5-pro"
```

### Ollama (Local, Free)

```toml
[llm]
model = "ollama/llama3.2"
# No api_key needed — Ollama runs locally
# base_url defaults to http://localhost:11434/v1
```

**Setup Ollama:**

```bash
# Install from https://ollama.ai
ollama serve           # Start server
ollama pull llama3.2   # Download model
```

### Multiple LLM Configs

Use different models for different purposes:

```toml
[llm]
api_key = "sk-..."
model = "claude-sonnet-4-20250514"   # Primary (high quality)

[llm.fast]
api_key = "sk-..."
model = "claude-haiku-4-5-20251001"            # Faster, cheaper

[llm.condenser]
api_key = "sk-..."
model = "gpt-4o-mini"             # For memory condensation
```

---

## Memory & Condensers

Condensers manage conversation history when it grows too large for the
LLM's context window.

### Available Condensers

| Condenser | Best For | Config |
|-----------|----------|--------|
| **smart** (default) | General use — adapts automatically | `type = "smart"` |
| **llm** | Long sessions needing high-quality summaries | `type = "llm"` |
| **observation_masking** | Preserving structure, masking old outputs | `type = "observation_masking"` |
| **recent** | Simple keep-N-recent approach | `type = "recent"` |
| **amortized** | Gradual forgetting of old context | `type = "amortized"` |
| **semantic** | Embedding-based relevance filtering | `type = "semantic"` |
| **llm_attention** | LLM-scored relevance prioritization | `type = "llm_attention"` |
| **noop** | Debugging — no condensation | `type = "noop"` |

### Configuration

```toml
[condenser]
type = "smart"    # Recommended default

# Or for long sessions with high-quality summarization:
# type = "llm"
# llm_config = "condenser"   # References [llm.condenser] section
# max_size = 100
# keep_first = 1
```

---

## Safety & Budget Controls

### Budget Limits

```toml
[core]
max_budget_per_task = 5.0   # USD per task (default)
max_iterations = 500        # Maximum agent steps
```

### Circuit Breaker

Automatically pauses the agent after:

- 5 consecutive errors
- 3 stuck detections (repeating actions)
- 10 high-risk actions

```toml
[agent]
enable_circuit_breaker = true   # Highly recommended
```

### Stuck Detection

The agent detects 6 types of stuck behavior:

1. Repeating identical actions
2. Repeating identical errors
3. Monologue loops (thinking without acting)
4. Action–observation oscillation patterns
5. Semantic loops (similar but not identical actions)
6. Context window error loops

### Graceful Shutdown

When budget/iteration limits are hit, the agent gets one final turn
to save progress:

```toml
[agent]
enable_graceful_shutdown = true   # Recommended
```

---

## MCP Integration

Forge supports the [Model Context Protocol](https://modelcontextprotocol.io/)
for connecting external tool servers.

### Configuration

```toml
[mcp]
# Stdio-based MCP server
[[mcp.servers]]
name = "my-mcp-server"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]

# SSE-based MCP server
[[mcp.servers]]
name = "remote-server"
url = "http://localhost:8080/sse"
```

### Using MCP Tools

Once configured, MCP tools appear in the agent's tool list automatically.
The agent can discover and use them based on the task context.

See [docs/mcp/integration_examples.md](mcp/integration_examples.md) for
detailed examples.

---

## Playbooks

Forge includes 16 built-in playbooks that activate automatically when your message matches
their trigger phrases, injecting specialist guidance into the agent's context window.

### Context Playbooks (auto-triggered)

| Playbook | Trigger phrases |
|---|---|
| **Debug** | `bug fix`, `debug`, `traceback`, `exception`, `error fix` |
| **Feature** | `implement feature`, `add feature`, `new feature`, `build feature` |
| **Refactoring** | `refactor`, `clean up code`, `restructure`, `technical debt` |
| **Documentation** | `document`, `add docs`, `write documentation`, `docstring` |
| **Testing** | `test`, `testing`, `pytest`, `jest`, `unittest`, `vitest` |
| **Code Review** | `/codereview`, `code review`, `review code`, `review pr` |
| **API** | `api`, `rest api`, `endpoint` |
| **Database** | `database`, `sql`, `migration` |
| **React** | `react`, `component`, `hooks` |
| **SSH** | `ssh`, `remote server`, `deploy` |
| **Add Agent** | `new agent`, `create playbook`, `add playbook` |

### Task Playbooks (invoked by `/command`)

Task playbooks collect variables from you before running:

| Command | What it does |
|---|---|
| `/address_pr_comments` | Reads PR URL + branch and resolves all reviewer comments |
| `/update_test` | Runs a test command on a branch and fixes failures |
| `/update_pr_description` | Rewrites the PR description to reflect the current diff |

Run a task playbook by typing the `/command` directly in the chat.

### Disabling Playbooks

Suppress specific playbooks for a session by setting `disabled_playbooks` in `settings.json`:

```json
{
  "disabled_playbooks": ["react", "ssh"]
}
```

You can also pass them via the API when creating a conversation.

### Custom Playbooks

Create your own playbooks in `~/.Forge/playbooks/` (user-level) or `.Forge/playbooks/`
(repo-level) using the same Markdown + frontmatter format. Type
`add playbook` in chat for a guided template.

---

## Advanced Configuration

### Runtime Settings

```toml
[runtime]
timeout = 120                        # Command timeout (seconds)
enable_auto_lint = false             # Auto-lint after edits
runtime_startup_env_vars = {}        # Inject env vars into runtime
```

### Agent Customization

```toml
[agent]
enable_browsing = true               # Web browsing capability
enable_llm_editor = false            # LLM-based code editing
enable_editor = true                 # Structure-aware editor
enable_cmd = true                    # Shell command execution
enable_think = true                  # Think tool for reasoning
enable_finish = true                 # Task completion tool
enable_history_truncation = true     # Truncate on context overflow
enable_summarize_context = false  # Agent-initiated condensation
```

---

## Performance Tuning

### Reduce Cost

1. **Use a cheaper model for condensation:**

   ```toml
   [llm.condenser]
   model = "gpt-4o-mini"
   
   [condenser]
   type = "llm"
   llm_config = "condenser"
   ```

2. **Enable prompt caching** (35% cost reduction):

   ```toml
   [llm]
   caching_prompt = true
   ```

3. **Lower context size:**

   ```toml
   [llm]
   max_message_chars = 20000
   ```

4. **Use faster models for simple tasks:**

   ```toml
   [llm]
   model = "claude-haiku-4-5-20251001"   # 3x cheaper than Sonnet
   ```

### Reduce Latency

1. **Use Ollama for zero-latency local inference:**

   ```toml
   [llm]
   model = "ollama/llama3.2"
   ```

2. **Increase timeout for complex tasks:**

   ```toml
   [runtime]
   timeout = 300
   ```

3. **Enable observation masking** (less data to process):

   ```toml
   [condenser]
   type = "observation_masking"
   attention_window = 50
   ```

### Improve Quality

1. **Use the best model:**

   ```toml
   [llm]
   model = "claude-sonnet-4-20250514"
   temperature = 0.0
   ```

2. **Keep more context:**

   ```toml
   [llm]
   max_message_chars = 50000
   max_input_tokens = 128000
   ```

3. **Use smart condenser:**

   ```toml
   [condenser]
   type = "smart"
   ```
