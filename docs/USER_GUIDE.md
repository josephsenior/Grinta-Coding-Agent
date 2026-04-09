# Grinta User Guide

> End-to-end guide: from installation to your first autonomous coding session.

Canonical local startup is the terminal CLI via `python -m backend.cli.entry`.
Any older references to `start_server.py`, `app.py`, or `uv run app serve` are obsolete.

## Table of Contents

1. [Installation](#installation)
2. [Configuration](#configuration)
3. [Your First Session](#your-first-session)
4. [Working with the Web UI](#working-with-the-web-ui)
5. [Working with the API](#working-with-the-api)
6. [LLM Providers](#llm-providers)
7. [Context Memory & Compactors](#context-memory--compactors)
8. [Safety & Budget Controls](#safety--budget-controls)
9. [MCP Integration](#mcp-integration)
10. [Playbooks](#playbooks)
11. [Advanced Configuration](#advanced-configuration)
12. [Performance Tuning](#performance-tuning)

---

## Installation

### Prerequisites

| Requirement | Version | Notes |
| --- | --- | --- |
| Python | 3.12+ | [python.org](https://python.org) |
| uv | 1.7+ | [docs.astral.sh/uv](https://docs.astral.sh/uv/) |
| Git | 2.30+ | [git-scm.com](https://git-scm.com/downloads) |

### Step 1: Clone and Install

```bash
git clone https://github.com/josephsenior/App.git
cd Grinta
uv sync
```

### Step 2: Configure

```bash
echo "LLM_API_KEY=sk-your-api-key-here" > .env
```

Your API keys must be set via `.env` files ensuring all subprocesses inherit credentials properly. Tune the rest of your agent parameters in `settings.json`.

### Step 3: Start

**Windows (recommended):**

```powershell
.\START_HERE.ps1
```

**Manual start (any OS):**

Terminal 1 — CLI:

```bash
uv run python -m backend.cli.entry
```

If you specifically need the raw HTTP backend for API/OpenAPI tooling, run `./start_backend.ps1` on Windows or `uv run python -m backend.execution.action_execution_server 3000 --working-dir "$PWD"`.

---

## Configuration

Grinta uses a multi-layered configuration system based on JSON and Environment Variables to ensure flexibility across different environments and prevent UI syncing ambiguity.

### Configuration Hierarchy

Configuration loads with this exact precedence (highest wins):

1. **Environment Variables**: Native shell vars, `.env.local`, and `.env` (best for API keys)
2. **`settings.json` at the app root**: The single source of truth for persisted settings (same file the Web UI reads and writes). Resolved via `APP_ROOT` if set, otherwise the directory the backend process was started from — **not** the “Open folder” workspace path.
3. **Pydantic defaults**: Internal safe fallbacks.

If the UI and CLI disagree, confirm the backend’s working directory (or set `APP_ROOT` to your checkout) so everyone targets the same `settings.json`.

### Getting Started

For standard use, rely on the Web UI to edit the repo’s `settings.json` (under the app root above). Protect API keys in `.env` at the Grinta project root (or via your shell environment):

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
| --- | --- |
| `llm.api_key` | `LLM_API_KEY` |
| `llm.model` | `LLM_MODEL` |
| `core.max_budget_per_task` | `CORE_MAX_BUDGET_PER_TASK` |
| `agent.enable_browsing` | `AGENT_ENABLE_BROWSING` |

---

## Your First Session

### 1. Start Grinta

```bash
uv run python -m backend.cli.entry
```

### 2. Start a Session

Launch the CLI in the project you want to work in. Grinta will keep project-local state under `.grinta/storage` for that checkout.

### 3. Describe Your Task

Type a natural language instruction:

```text
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

- **Review diffs** with your editor or `git diff`
- **Resume work** later with the session commands in the CLI
- **Interrupt** the agent at any time

### Example Tasks

| Task | Typical Cost | Iterations |
| --- | --- | --- |
| Fix a specific bug | $0.03–0.10 | 2–5 |
| Implement a function | $0.05–0.20 | 3–8 |
| Add tests for a module | $0.10–0.30 | 5–15 |
| Refactor a class | $0.15–0.50 | 8–20 |
| Build a feature end-to-end | $0.30–1.00 | 10–30 |

---

## Working with the Web UI

The primary interface is the React app served with the backend (default [http://localhost:3000](http://localhost:3000)).
Use it to manage conversations, settings, confirmations, and workspace changes. The same REST and
Socket.IO APIs power automation via the Python package `client` (see tests under
`backend/tests/unit/client/` and `scripts/test_agent_via_sockets.py`).

---

## Working with the API

Grinta exposes a REST + Socket.IO API on port 3000.

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
| --- | --- | --- |
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

[llm.compactor]
api_key = "sk-..."
model = "gpt-4o-mini"             # Current config name for compaction workloads
```

---

## Context Memory & Compactors

Context memory is compacted when conversation history grows too large for the
LLM's context window. Grinta now uses compactor as the canonical term in code,
docs, and persisted config.

### Available Compactors

| Compactor | Best For | Current Config |
| --- | --- | --- |
| **smart** (default) | General use — adapts automatically | `type = "smart"` |
| **structured** | Long sessions needing high-quality summaries | `type = "structured"` |
| **observation_masking** | Preserving structure, masking old outputs | `type = "observation_masking"` |
| **recent** | Simple keep-N-recent approach | `type = "recent"` |
| **amortized** | Gradual pruning of old context | `type = "amortized"` |
| **noop** | Debugging — no condensation | `type = "noop"` |

### Compactor Configuration

```toml
[compactor]
type = "smart"    # Recommended default

# Or for long sessions with high-quality structured summaries:
# type = "structured"
# llm_config = "compactor"   # References the example [llm.compactor] section above
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

### Long-Session Stuck Detection

The agent detects 6 types of stuck behavior:

1. Repeating identical actions
2. Repeating identical errors
3. Monologue loops (thinking without acting)
4. Action–observation oscillation patterns
5. Semantic loops (similar but not identical actions)
6. Context window error loops

Stuck detection is **enabled by default**. If you need to disable it for
a specific session:

```json
{
  "stuck_detection_enabled": false
}
```

### Graceful Shutdown

When budget/iteration limits are hit, the agent gets one final turn
to save progress:

```toml
[agent]
enable_graceful_shutdown = true   # Recommended
```

---

## Reliability & Long-Session Settings

These settings are critical for unattended or long-running coding sessions.
All are **enabled by default** for daily-driver reliability.

### Pending Action Timeout (Watchdog)

If a tool call doesn't produce an observation within the timeout, the
agent receives an error and can retry or move on. This prevents sessions
from stalling indefinitely on hung tools.

```json
{
  "pending_action_timeout": 120.0
}
```

- **Default**: `120` seconds (2 minutes)
- **MCP tools**: Automatically use a higher floor of `180` seconds to
  accommodate cold starts (npx, remote servers)
- **Disable**: Set to `0` (not recommended for unattended sessions)

### Auto-Retry on Error

When enabled, the agent automatically retries after recoverable errors
(rate limits, transient API failures, timeouts) without waiting for
manual confirmation.

```json
{
  "auto_retry_on_error": true
}
```

- **Default**: `true`
- Exponential backoff: 8s base delay, up to 64s max wait
- Rate-limit errors get 2× base delay automatically
- Max 5 retry attempts per failure

### Stuck Detection

Six-strategy pattern detector that catches infinite loops, repeating
errors, monologue spirals, and context-window traps. When stuck is
detected, the circuit breaker escalates (warning → replan → pause → stop).

```json
{
  "stuck_detection_enabled": true
}
```

- **Default**: `true`
- Strategies: action-observation repeat, action-error repeat, monologue,
  A-B-A-B oscillation, context-window trap, think-only loop
- **Circuit breaker trip**: 3 stuck detections → agent stops
- **Progress signals**: Agent can decrement stuck count by reporting progress

### Recommended Long-Session Configuration

For overnight or multi-hour unattended sessions, use these settings
together in `settings.json`:

```json
{
  "max_budget_per_task": 10.0,
  "pending_action_timeout": 120.0,
  "auto_retry_on_error": true,
  "stuck_detection_enabled": true,
  "enable_circuit_breaker": true,
  "enable_graceful_shutdown": true,
  "max_iterations": 500
}
```

This configuration ensures:

- **Cost control**: $10 cap with alerts at 50%/80%/90%
- **Hang recovery**: 2-minute watchdog on every tool call
- **Error recovery**: Automatic retry with exponential backoff
- **Loop prevention**: 6-strategy stuck detection with circuit breaker
- **Graceful exit**: Agent summarizes progress before forced shutdown

---

## MCP Integration

Grinta supports the [Model Context Protocol](https://modelcontextprotocol.io/)
for connecting external tool servers.

### MCP Configuration

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

Grinta includes 16 built-in playbooks that activate automatically when your message matches
their trigger phrases, injecting specialist guidance into the agent's context window.

Playbooks can come from three places:

- built-in playbooks shipped with Grinta
- user playbooks in `~/.grinta/playbooks/`
- repository playbooks in `.grinta/playbooks/`

### Context Playbooks (auto-triggered)

| Playbook | Trigger phrases |
| --- | --- |
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

### How Trigger Matching Works

Auto-triggered playbooks use a two-tier matcher:

1. **Substring match first**: fast case-insensitive containment check
2. **Semantic fallback second**: word-overlap similarity when no substring match fires

The fallback is intentionally conservative so short triggers do not activate irrelevant playbooks too easily.

If you want exact substring matching only, set this in the playbook frontmatter:

```yaml
strict_trigger_matching: true
```

### Task Playbooks (invoked by `/command`)

Task playbooks collect variables from you before running:

| Command | What it does |
| --- | --- |
| `/address_pr_comments` | Reads PR URL + branch and resolves all reviewer comments |
| `/update_test` | Runs a test command on a branch and fixes failures |
| `/update_pr_description` | Rewrites the PR description to reflect the current diff |

Run a task playbook by typing the `/command` directly in the chat.

Task playbooks are recognized automatically from their metadata. If a playbook declares `inputs`, Grinta treats it as a task playbook and exposes it through the `/name` invocation pattern.

### Disabling Playbooks

Suppress specific playbooks for a session by setting `disabled_playbooks` in `settings.json`:

```json
{
  "disabled_playbooks": ["react", "ssh"]
}
```

You can also pass them via the API when creating a conversation.

### Custom Playbooks

Create your own playbooks in `~/.grinta/playbooks/` (user-level) or `.grinta/playbooks/`
(repo-level) using the same Markdown + frontmatter format. Type
`add playbook` in chat for a guided template.

### Frontmatter Patterns

The frontmatter determines how Grinta interprets a playbook:

- `triggers` present -> auto-triggered knowledge playbook
- `inputs` present -> task playbook invoked by `/command`
- neither present -> repository knowledge playbook

Example auto-triggered playbook:

```markdown
---
name: sql-review
triggers: ["sql", "migration", "query plan"]
strict_trigger_matching: false
---

Review migrations carefully. Check rollback safety, indexes, and data backfills.
```

Example task playbook:

```markdown
---
name: address_pr_comments
inputs:
   - name: pr_url
      description: Pull request URL
   - name: branch
      description: Branch to update
---

Resolve reviewer comments, rerun relevant checks, and summarize the changes.
```

### Auto-Imported Playbooks

Grinta also recognizes a small set of external convention files and imports them as repository-scoped playbooks:

| File | Imported As |
| --- | --- |
| `.cursorrules` | repository playbook named `cursorrules` |
| `agents.md` / `agent.md` | repository playbook named `agents` |

That means teams can carry forward lightweight guidance from adjacent tooling without manually rewriting everything into a new format on day one.

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

1. **Use a cheaper model for compaction:**

   ```toml
   [llm.compactor]
   model = "gpt-4o-mini"
   
   [compactor]
   type = "structured"
   llm_config = "compactor"
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

3. **Enable outcome masking** (less data to process):

   ```toml
   [compactor]
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

3. **Use smart compactor:**

   ```toml
   [compactor]
   type = "smart"
   ```
