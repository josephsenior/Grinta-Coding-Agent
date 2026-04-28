# Orchestrator Agent

## Overview

Orchestrator is App's flagship autonomous coding agent, optimized for the beta launch. It uses a **ReAct (Reasoning + Acting)** approach to solve coding tasks through iterative observation and action cycles.

## Key Features

- ✅ **Structure-Aware Editing** - Parses code via Tree-sitter (45+ languages)
- ✅ **Tool Execution** - Edit files, run commands, browse web
- ✅ **Self-Correction** - Learns from errors and retries
- ✅ **Circuit Breaker** - Auto-pauses on repeated failures (safety)
- ✅ **Cost Tracking** - Monitors LLM usage and costs
- ✅ **Real-Time Streaming** - Shows thinking process live

## How It Works

### The ReAct Loop

```
1. Observe current state
   ↓
2. Reason about next action
   ↓
3. Act (edit file, run command, etc.)
   ↓
4. Observe result
   ↓
5. Repeat until task complete
```

### Example: "Fix bug in main.py"

```
Step 1: Read file
Action: FileReadAction("main.py")
Observation: File content shows undefined variable on line 42

Step 2: Analyze issue
Reasoning: Variable 'count' used before definition

Step 3: Fix code
Action: FileEditAction(path="main.py", ...)
Observation: File edited successfully

Step 4: Verify fix
Action: CmdRunAction("python main.py")
Observation: Program runs without errors

Step 5: Complete
Action: PlaybookFinishAction("Fixed undefined variable bug")
```

## Available Actions

### File Operations

**FileReadAction** - Read file contents:
```python
FileReadAction(path="src/main.py")
```

**FileWriteAction** - Create new file:
```python
FileWriteAction(
    path="src/utils.py",
    content="def helper():\n    pass"
)
```

**FileEditAction** - Edit existing file (structure-aware):
```python
FileEditAction(
    path="src/main.py",
    old_content="def old_function():",
    new_content="def new_function():",
    start_line=10,
    end_line=15
)
```

### Non-Code Editing Protocol

For non-code files, prefer document-oriented editing over raw substring replacement:

- `edit_mode="format"` for structured files (`json`, `yaml`, `toml`) using parser mutate/serialize.
- `edit_mode="section"` for anchor-bounded document sections (for example markdown headings).
- `edit_mode="range"` for deterministic line-range edits, optionally guarded by `expected_hash`.
- `edit_mode="patch"` for unified-diff hunk application with strict context matching.
- `edit_mode="replace"` as compatibility fallback for legacy `old_str`/`new_str` edits.

### Command Execution

**CmdRunAction** - Run shell commands:
```python
CmdRunAction(
    command="pytest tests/",
    thought="Running tests to verify changes"
)
```

### Browser Automation

**Native browser tool (`browser`)** — In-process automation via the optional
[`browser-use`](https://github.com/browser-use/browser-use) Python package (no nested `Agent`; Grinta stays the only LLM policy).

1. Install deps: `uv sync --group browser` (adds `browser-use` to the environment).
2. Install Chromium for automation **before** relying on the tool: `uvx browser-use install` (typical on a fresh machine). Pre-installing avoids slow or failing first launches under Grinta’s session start timeout.
3. Enable in agent config: `enable_browsing = true` and `enable_native_browser = true`.

### Communication

**MessageAction** - Communicate with user:
```python
MessageAction(
    content="I've completed the changes. Please review the diff."
)
```

**PlaybookFinishAction** - Mark task complete:
```python
PlaybookFinishAction(
    outputs={"files_modified": ["main.py", "tests.py"]}
)
```

## Configuration

### Basic Configuration

```toml
[agent]
name = "Orchestrator"
max_iterations = 100  # Safety limit

[llm]
model = "claude-sonnet-4-20250514"
temperature = 0.0
max_output_tokens = 8000
```

### Advanced Options

```toml
[agent.orchestrator]
# Confirmation mode
confirmation_mode = true  # Ask before destructive actions

# Memory
memory_enabled = true
memory_max_threads = 20

# Retry logic (inherited from LLM config)
[llm]
num_retries = 5
retry_min_wait = 8
retry_max_wait = 64
```

## Prompt Engineering

### System Prompt Structure

The Orchestrator agent uses a carefully crafted prompt:

```
1. Role definition ("You are a senior software engineer...")
2. Available tools (text_editor, terminal tools, browse, etc.)
3. Output format (ReAct style: Thought → Action → Observation)
4. Best practices (read before edit, test changes, etc.)
5. Examples (few-shot learning)
```

**File:** `App/engines/orchestrator/prompts.py`

### Optimizations

- **Compact prompt:** 166 lines (optimized from 300+)
- **Few-shot examples:** 3 examples of common patterns
- **Tool descriptions:** Clear, concise, actionable
- **Error handling:** Explicit retry instructions

## Safety Features

### 1. Circuit Breaker

**Automatically pauses agent if:**
- 3 consecutive failures
- Same action repeated 5 times (stuck detection)
- High-risk action without confirmation

**File:** `App/controller/circuit_breaker.py`

### 2. Confirmation Mode

**User confirmation required for:**
- Deleting files
- Running destructive commands (`rm -rf`, `DROP TABLE`, etc.)
- Installing packages
- Network requests to external services

### 3. Runtime Execution

**All actions run in the local runtime environment:**
- Isolated file system
- Limited network access
- Resource constraints (CPU, memory)
- No access to host system

## Performance

### Typical Performance

| Task Type | Actions | Time | Cost |
|-----------|---------|------|------|
| Simple bug fix | 2-3 | 10-15s | $0.05 |
| Feature implementation | 5-10 | 30-60s | $0.15 |
| Complex refactoring | 10-20 | 1-3min | $0.30 |

### Optimization Tips

**1. Use faster models:**
```toml
[llm]
model = "claude-haiku-4-5-20251001"  # 2x faster, 1/3 cost
```

**2. Enable caching:**
```toml
[llm]
caching_prompt = true  # 35% cost reduction
```

**3. Reduce context:**
```toml
[llm]
max_message_chars = 20000  # Less context = faster + cheaper
```

## Debugging

### Enable Debug Logging

```bash
LOG_LEVEL=DEBUG uv run python -m App.server.listen
```

### Trace Agent Steps

```bash
# Watch agent decisions
tail -f logs/App.log | grep "Orchestrator"

# Output shows:
# [Step 1] Thought: I need to read the file
# [Step 1] Action: FileReadAction(path="main.py")
# [Step 1] Observation: File contains 50 lines...
# [Step 2] Thought: I found the bug on line 42
# [Step 2] Action: FileEditAction(...)
```

### Common Issues

**Agent stuck in loop:**
- Circuit breaker will auto-pause after 5 identical actions
- Check `stuck_detector.py` logs

**File edits failing:**
- Verify file exists
- Check file permissions
- Review edit diff (might have syntax errors)

**Commands not executing:**
- Verify local runtime process is healthy
- Check backend logs for runtime startup errors

## Extending the Orchestrator

### Add Custom Tools

```python
# Grinta/engines/orchestrator/tools.py

CUSTOM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "analyze_database",
            "description": "Analyze database schema",
            "parameters": {...}
        }
    }
]
```

### Custom Prompt

```python
# Grinta/engines/orchestrator/prompts.py

CUSTOM_SYSTEM_PROMPT = """
You are a specialized agent for...
"""
```

## Comparison to Other Agents

| Feature | Orchestrator | PlannerAgent | BrowseAgent |
|---------|---------|--------------|-------------|
| **Code editing** | ✅ Excellent | ⚠️ Basic | ❌ No |
| **Planning** | ⚠️ Implicit | ✅ Explicit | ❌ No |
| **Browser** | ✅ Yes | ❌ No | ✅ Specialized |
| **Best for** | Coding tasks | Complex multi-step | Web research |
| **Beta status** | ✅ Enabled | ⚠️ Available | ✅ Enabled |

## Best Practices

### 1. Be Specific in Prompts

**Good:**
```
Fix the TypeError on line 42 in src/utils.py where 'count' is
used before definition. Initialize it to 0 at the start of the function.
```

**Bad:**
```
Fix the bug
```

### 2. Provide Context

**Good:**
```
Add user authentication to this Flask app. We're using SQLAlchemy
for the database. Follow the existing pattern in models/user.py.
```

**Bad:**
```
Add auth
```

### 3. Review Changes

- Always review file diffs before approving
- Check test results
- Verify no unintended changes

### 4. Use Iterations

```
Prompt 1: "Create the basic structure"
Prompt 2: "Add error handling"
Prompt 3: "Add tests"

vs.

Prompt: "Build complete app with error handling and tests"
```

Small iterations = better results

## Advanced Usage

### With MCP Servers

The Orchestrator can use MCP tools:

```
# Available by default:
- context7 (library docs)
- shadcn (UI components)
- github (repos, issues, PRs)
- fetch (HTTP requests)
- rigour (local governance / quality gates via @rigour-labs/mcp; no API key)
- exa (Exa hosted MCP / web search; optional EXA_API_KEY in .env)

# Example prompt:
"Use the fetch tool to get data from https://api.example.com
and save it to data.json"
```

### With Memory System

The Orchestrator remembers context across conversations:

```
Conversation 1: "Build a todo app with React"
Conversation 2: "Add user authentication to the todo app"
# Agent remembers the todo app structure
```

## Metrics

**Orchestrator-specific metrics:**

```
orchestrator_actions_executed{type="FileEditAction"}  # File edits
orchestrator_actions_executed{type="CmdRunAction"}    # Commands run
orchestrator_success_rate                             # Success percentage
orchestrator_avg_iterations                           # Iterations per task
```

## References

- [Architecture](../../docs/ARCHITECTURE.md) - System design
- [API Reference](../../docs/API_REFERENCE.md) - API docs
- [Troubleshooting](../../docs/TROUBLESHOOTING.md) - Common issues
- [ReAct Paper](https://arxiv.org/abs/2210.03629) - Original ReAct research

For questions or issues, see [Troubleshooting](../../docs/TROUBLESHOOTING.md) or open a GitHub issue.
