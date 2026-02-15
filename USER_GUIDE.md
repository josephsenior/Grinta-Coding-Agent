# Forge User Guide

Complete guide to using Forge for everyday coding tasks.

## Table of Contents

1. [First Time Setup](#first-time-setup)
2. [LLM Configuration](#llm-configuration)
3. [Autonomy Modes](#autonomy-modes)
4. [Playbooks](#playbooks)
5. [Memory & Context Management](#memory--context-management)
6. [TUI Usage](#tui-usage)
7. [Advanced Configuration](#advanced-configuration)
8. [Troubleshooting](#troubleshooting)

## First Time Setup

### Quick Start

1. **Windows**: Run `.\START_HERE.ps1` in PowerShell (installs everything automatically)
2. **Manual**: Run `poetry install` then `python start_server.py`
3. **TUI**: Run `python -m backend.tui` in a separate terminal

### Initial Configuration

Copy the template config and set your API key:

```bash
cp config.template.toml config.toml
# Edit config.toml and set your LLM API key
```

## LLM Configuration

### Cloud Models

#### OpenAI
```toml
[llm]
model = "gpt-4o"
api_key = "sk-your-openai-key"
```

#### Anthropic
```toml
[llm]
model = "claude-3-5-sonnet-20241022"
api_key = "sk-ant-your-anthropic-key"
```

#### Google Gemini
```toml
[llm]
model = "gemini/gemini-1.5-pro"
api_key = "your-google-api-key"
```

### Local Models with Ollama

Forge has native Ollama support. The `ollama/` prefix is automatically recognized
and the model name is correctly stripped before being sent to Ollama's API.

1. **Install Ollama**: Download from [ollama.ai](https://ollama.ai)
2. **Start Ollama**: `ollama serve` (runs on port 11434 by default)
3. **Pull a model**: `ollama pull llama3.2`
4. **Configure Forge**:

```toml
[llm]
model = "ollama/llama3.2"
# base_url defaults to http://localhost:11434/v1 for Ollama models
# api_key is not required for local models
temperature = 0.1       # Lower for more consistent code
max_output_tokens = 4000
```

> **Note**: You do NOT need to set `api_key` or `base_url` for Ollama models.
> Forge auto-detects the `ollama/` prefix, strips it before sending to the API,
> and defaults the base URL to `http://localhost:11434/v1`.

**Recommended local models**:

- `ollama/llama3.2`: Good balance of speed/quality
- `ollama/deepseek-coder`: Excellent for coding tasks
- `ollama/qwen2.5-coder`: Strong code completion
- `ollama/codellama`: Specialized for code generation

**Hardware requirements**:
- **Minimum**: 8GB RAM, CPU-only (slow but works)
- **Recommended**: 16GB+ RAM with NVIDIA/AMD GPU for 10-100x speedup
- **Context**: Larger `max_output_tokens` = slower but better quality output

### Other Local Setups (OpenAI-Compatible)

Any server exposing an OpenAI-compatible API at `/v1/chat/completions` works.
Forge auto-detects localhost URLs and skips API key validation.

#### LM Studio

```toml
[llm]
model = "your-model-name"              # Use the model name shown in LM Studio
base_url = "http://localhost:1234/v1"
```

#### vLLM

```toml
[llm]
model = "your-model-name"
base_url = "http://localhost:8000/v1"
```

## Autonomy Modes

Forge has three autonomy levels you can choose from:

### 1. Supervised Mode (Default)
```toml
[agent]
autonomy_level = "supervised"
```

- **What it does**: Agent asks for permission before every action
- **When to use**: Learning Forge, working on critical code, debugging sessions
- **Pros**: Maximum control, see every step
- **Cons**: Requires constant interaction

### 2. Balanced Mode (Recommended)
```toml
[agent]
autonomy_level = "balanced"
```

- **What it does**: Agent runs automatically but asks permission for high-risk actions
- **High-risk actions**: System commands, file deletions, network requests, installing packages
- **When to use**: Most everyday coding tasks
- **Pros**: Good balance of speed and safety

### 3. Full Autonomy Mode
```toml
[agent]
autonomy_level = "full"
```

- **What it does**: Agent runs completely automatically
- **Safety**: Circuit breaker still active (stops after errors/stuck detection)
- **When to use**: Simple tasks, trusted environments, long-running sessions
- **Pros**: Fastest, no interruptions
- **Cons**: Less control, relies on safety systems

### Safety Settings (All Modes)

These safety features are always active:

```toml
[agent]
# Circuit breaker stops agent after repeated failures
enable_circuit_breaker = true

# Give agent one final turn to save work when limits hit
enable_graceful_shutdown = true

# Maximum cost per task to prevent runaway charges
max_budget_per_task = 5.0  # $5 USD default

# Maximum iterations before auto-stop
max_iterations = 500
```

### Circuit Breaker (Deep Dive)

The circuit breaker is an autonomous safety system that automatically pauses the agent
when it detects anomalous behavior. It monitors four independent trip conditions:

#### Trip Conditions

| Condition | Default Threshold | Action | Description |
| --- | --- | --- | --- |
| Consecutive errors | 5 errors | Pause | Same error repeated without recovery |
| High-risk actions | 10 actions | Pause | Too many dangerous commands (rm, sudo, etc.) |
| Stuck detections | 3 detections | **Stop** | Agent stuck in loops (escalated severity) |
| Error rate | 50% of last 10 | Pause | Overall failure rate too high |

#### Tuning Thresholds

```toml
[agent]
enable_circuit_breaker = true

# How many consecutive errors before pausing (default: 5)
max_consecutive_errors = 5

# How many high-risk actions before pausing (default: 10)
max_high_risk_actions = 10

# How many stuck detections before stopping (default: 3)
max_stuck_detections = 3
```

#### Environment Variable Overrides

For the low-level network/service circuit breaker (separate from agent safety):

```bash
FORGE_CB_FAILURE_THRESHOLD=3    # Failures before opening circuit
FORGE_CB_BASE_OPEN_SECONDS=2    # Initial backoff duration
FORGE_CB_MAX_OPEN_SECONDS=60    # Maximum backoff cap
FORGE_CB_HALF_OPEN_PROBES=1     # Probes allowed in half-open state
```

### Stuck Detection (Deep Dive)

Forge uses **6 independent strategies** to detect when the agent is stuck:

1. **Action-Observation Loop**: Same action producing same result 4+ times
2. **Action-Error Loop**: Same action causing same error 3+ times
3. **Agent Monologue**: Agent sending identical messages without doing anything
4. **Pattern Repetition**: Alternating A-B-A-B action patterns (6+ events)
5. **Context Window Loop**: Repeated condensation without progress (10+ times)
6. **Semantic Loop**: Different actions but same no-progress outcome
   - Measures *intent diversity* (< 0.4 = low variety) and *failure rate* (> 0.6 = high failures)
   - Catches: trying different commands that all fail the same way

Plus two additional safety checks:
- **Token Repetition**: Identical agent messages output 3+ times
- **Cost Acceleration**: Context growing >10k tokens in 5 steps, or >100k total with continued growth

When stuck is detected, the circuit breaker increments its stuck counter.
After 3 stuck detections (default), the agent is **stopped** (not just paused)
with a recommendation to restart with a different strategy.

## Playbooks

Playbooks are pre-written instructions for common tasks. Forge has 18 built-in playbooks:

### Available Playbooks

| Playbook | Purpose | Usage |
|---|---|---|
| `code-review` | Comprehensive code review | "Review this PR using the code-review playbook" |
| `testing` | Add tests to existing code | "Add tests for this module using the testing playbook" |
| `api` | Create REST APIs | "Build an API endpoint with the api playbook" |
| `database` | Database schema work | "Design the database schema with the database playbook" |
| `react` | React component development | "Create React components with the react playbook" |
| `ssh` | SSH configuration and troubleshooting | "Set up SSH keys using the ssh playbook" |
| `add_repo_inst` | Add instructions to repositories | "Add setup instructions with the add_repo_inst playbook" |

### Using Playbooks

#### Option 1: Mention in conversation
```
"Can you review this code using the code-review playbook?"
"Add comprehensive tests using the testing playbook"
```

#### Option 2: Disable specific playbooks
```toml
[agent]
disabled_playbooks = ["react", "swift-linux"]  # Skip these playbooks
```

### Custom Playbooks

Create `.md` files in `backend/playbooks/`:

```markdown
# My Custom Playbook

## Objective
Brief description of what this playbook accomplishes.

## Steps
1. First step
2. Second step
3. Final step

## Best Practices
- Use consistent naming
- Add error handling
- Write documentation
```

## Memory & Context Management

Forge uses **condensers** to manage conversation history when context gets too large.

### Condenser Types

#### 1. Smart Condenser (Default)
```toml
[condenser]
type = "smart"
```
- **What it does**: Automatically picks the best strategy based on context
- **Best for**: Most users, handles all scenarios intelligently

#### 2. LLM Summarizing
```toml
[condenser]
type = "llm"
llm_config = "condenser"  # Can use cheaper model
keep_first = 3           # Always keep first N events
max_size = 150           # Summarize when history exceeds this
```
- **What it does**: Uses LLM to create intelligent summaries
- **Best for**: Long coding sessions, complex context
- **Cost**: Uses additional LLM calls for summarization

#### 3. Recent Events
```toml
[condenser]
type = "recent"
keep_first = 5     # Keep initial task description + first few events
max_events = 100   # Keep last 100 events, discard older ones
```
- **What it does**: Simple sliding window, keeps recent events
- **Best for**: Cost-conscious users, simple tasks
- **Pros**: No LLM cost, fast
- **Cons**: May lose important historical context

#### 4. Observation Masking
```toml
[condenser]
type = "observation_masking"
attention_window = 50  # Don't mask observations in last 50 events
```
- **What it does**: Keeps full event structure, masks old observation content
- **Best for**: Debugging, need to see full action/observation flow
- **Pros**: Preserves session structure

#### 5. No Condensing (Debug)
```toml
[condenser]
type = "noop"
```
- **What it does**: Keeps full history, no condensing
- **Best for**: Debugging condenser issues, short sessions only
- **Warning**: Will hit context limits on long sessions

### Advanced Memory Settings

#### Multiple LLM Configs
```toml
[llm]  # Main model
model = "claude-3-5-sonnet-20241022"
api_key = "your-key"

[llm.condenser]  # Cheaper model for summarization
model = "gpt-4o-mini"
api_key = "your-openai-key"
temperature = 0.1
```

#### Vector Memory (Optional)
```toml
[agent]
enable_vector_memory = true  # Remembers similar past conversations
```

Requires: `pip install chromadb` or `poetry install --extras memory`

## TUI Usage

### Navigation

| Key | Action |
|---|---|
| `Ctrl+C` | Quit application |
| `Tab` | Navigate between widgets |
| `Enter` | Select/confirm |
| `Escape` | Go back/cancel |
| `↑/↓` | Scroll in lists |
| `Ctrl+L` | Clear screen |

### Home Screen

- **View conversations**: Scroll through your conversation list
- **Create new**: Press enter on "Create New Conversation"
- **Resume**: Select any existing conversation

### Chat Screen

- **Type messages**: Type in the bottom input box
- **Approve/Reject**: Use the confirmation bar when agent asks
- **View status**: Top status bar shows agent state, model, cost
- **Pause/Resume**: If agent gets stuck, use traffic control

### Settings Screen

- **LLM Model**: Change model on the fly
- **API Keys**: Update credentials
- **Agent Behavior**: Modify autonomy level
- **Condensers**: Switch memory strategies

### Diff Viewer

When agent makes file changes, view side-by-side diffs:
- **Left**: Original file
- **Right**: Modified file
- **Colors**: Green (added), red (removed), yellow (modified)

## Advanced Configuration

### Performance Tuning

```toml
[core]
# Maximum iterations before auto-stop
max_iterations = 500

# Budget per task (prevents runaway costs)
max_budget_per_task = 10.0  # $10 USD

# Enable browser for web-related tasks
enable_browser = true

[runtime]
# Runtime timeout for long-running commands
timeout = 300  # 5 minutes

# Enable auto-linting after file edits
enable_auto_lint = true

[agent]
# Enable command execution
enable_cmd = true

# Enable file editing
enable_editor = true

# Enable browsing
enable_browsing = true
```

### Event Stream Tuning

For high-throughput or memory-constrained environments:

```toml
[event_stream]
max_queue_size = 1000     # Reduce from default 2000
drop_policy = "drop_oldest"  # or "drop_newest", "block"
hwm_ratio = 0.7          # Warning at 70% queue full
workers = 4              # Reduce parallel event processing
```

### Logging Configuration

```toml
[core]
# Enable debug logging
debug = true

# Disable colored output (for log files)  
disable_color = true

# Save chat trajectories
save_trajectory_path = "./sessions"
save_screenshots_in_trajectory = false  # Keeps files smaller
```

## Troubleshooting

### Common Issues

#### 1. "Module not found" errors
```bash
# Reinstall dependencies
poetry lock --no-update
poetry install
```

#### 2. Port already in use
```bash
# Kill process using port 3000
netstat -ano | findstr :3000
taskkill /PID <PID_NUMBER> /F

# Or use different port
python start_server.py --port 3001
```

#### 3. LLM API errors
- Check your API key in `config.toml`
- Verify your account has credits/quota
- For Ollama: ensure `ollama serve` is running

#### 4. Agent gets stuck
- Agent has built-in stuck detection (6 strategies)
- Circuit breaker will auto-pause after repeated failures
- Use "Resume" button or restart if needed

#### 5. High memory usage
- Switch to `recent` condenser for lower memory usage
- Reduce `max_events` in condenser config
- Lower `event_stream.max_queue_size`

#### 6. Slow performance
- Use a local model (Ollama) for faster responses
- Reduce `temperature` for more consistent output
- Enable `runtime.enable_auto_lint = false` if not needed

### Debug Mode

Enable verbose logging:

```toml
[core]
debug = true
```

Or set environment variable:
```bash
export FORGE_DEBUG=1
```

### Health Checks

Check if Forge is running properly:
- **Backend health**: http://localhost:3000/api/health/live
- **System info**: http://localhost:3000/server_info  
- **API docs**: http://localhost:3000/docs

### Getting Help

1. **Check logs**: Look at console output for error messages
2. **Health endpoint**: Visit `/api/health/ready` for system status
3. **GitHub issues**: [Report bugs or request features](https://github.com/josephsenior/Forge/issues)
4. **Community**: [Join discussions](https://github.com/josephsenior/Forge/discussions)

### Performance Tips

1. **Choose the right model**:
   - `gpt-4o-mini`: Fastest, cheapest
   - `claude-3-5-sonnet`: Best code quality
   - `llama3.2` (local): No API costs

2. **Optimize for your workflow**:
   - **Short tasks**: Use `noop` condenser
   - **Long sessions**: Use `smart` or `llm` condenser
   - **Cost-conscious**: Use `recent` condenser + local models

3. **Tune safety vs speed**:
   - **Maximum safety**: `supervised` mode + circuit breaker
   - **Balanced**: `balanced` mode (default)
   - **Maximum speed**: `full` autonomy + higher budgets