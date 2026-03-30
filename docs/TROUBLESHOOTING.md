# Troubleshooting Guide

Common issues, their causes, and proven solutions.

---

## Table of Contents

1. [Installation Issues](#installation-issues)
2. [Startup Failures](#startup-failures)
3. [LLM Provider Issues](#llm-provider-issues)
4. [Agent Behavior Issues](#agent-behavior-issues)
5. [Runtime Issues](#runtime-issues)
6. [Web UI Issues](#web-ui-issues)
7. [Performance Issues](#performance-issues)
8. [Windows-Specific Issues](#windows-specific-issues)
9. [Diagnostic Commands](#diagnostic-commands)

---

## Installation Issues

### uv not found

**Symptom:** `uv: command not found` or `'uv' is not recognized`

**Fix:**
```powershell
# Windows — add to PATH for current session
$env:Path += ";$env:APPDATA\Python\Scripts"

# Or install uv globally
pip install uv
```

### Python version mismatch

**Symptom:** `Python 3.12+ is required`

**Fix:** Install Python 3.12+ from [python.org](https://python.org). Verify:
```bash
python --version   # Must be 3.12+
```

### Lock file / dependency drift

**Symptom:** `uv sync` fails with dependency resolution errors

**Fix:**
```bash
uv lock
uv sync --no-install-project
```

### Git not found

**Symptom:** Warning about Git not being installed

**Fix:** Install Git from [git-scm.com](https://git-scm.com/downloads).
The agent needs Git for version tracking and diff operations.

---

## Startup Failures

### Port already in use

**Symptom:** `Address already in use: port 3000`

**Fix:**
```bash
# Find the process using port 3000
# Windows:
netstat -ano | findstr :3000
taskkill /PID <pid> /F

# Linux/macOS:
lsof -i :3000
kill -9 <pid>
```

Or change the port:
```bash
python start_server.py --port 3001
```
Then open `http://localhost:3001` in your browser.

### Config file errors

**Symptom:** `ValidationError` on startup

**Fix:**
1. Verify `config.toml` syntax (use a TOML validator)
2. Check that all values match expected types
3. Start fresh: `cp config.template.toml config.toml`

### Missing API key

**Symptom:** `LLM API key not configured` or 401 errors from LLM provider

**Fix:** Set your API key in `config.toml`:
```toml
[llm]
api_key = "sk-your-key-here"
```

Or via environment variable:
```bash
export LLM_API_KEY="sk-your-key-here"
```

---

## LLM Provider Issues

### Rate limiting (429 errors)

**Symptom:** `Rate limit exceeded` or `429 Too Many Requests`

**Fix:** App has built-in retry with exponential backoff. If it persists:
```toml
[llm]
num_retries = 10
retry_min_wait = 15
retry_max_wait = 120
retry_multiplier = 2.0
```

### Context window exceeded

**Symptom:** `context_length_exceeded` or `prompt is too long`

**Fix:** Enable history truncation and/or use a compactor. The persisted config
section name is `[compactor]`:
```toml
[agent]
enable_history_truncation = true

[compactor]
type = "smart"
```

### Model not found

**Symptom:** `Model 'xxx' not found` or `Invalid model`

**Fix:** Verify the model name matches the provider's naming:
```toml
[llm]
# Anthropic
model = "claude-sonnet-4-20250514"
# OpenAI
model = "gpt-4o"
# Google
model = "gemini/gemini-2.5-pro"
# Ollama
model = "ollama/llama3.2"
```

### Ollama connection refused

**Symptom:** `Connection refused` when using Ollama

**Fix:**
```bash
# 1. Start Ollama server
ollama serve

# 2. Pull the model
ollama pull llama3.2

# 3. Verify it's running
curl http://localhost:11434/v1/models
```

---

## Agent Behavior Issues

### Agent stuck in a loop

**Symptom:** Agent repeats the same action or oscillates between actions

**Cause:** The agent is in a stuck pattern. App has 6 detection strategies
for this.

**Fix:**
1. The circuit breaker will auto-pause after threshold is hit
2. If it doesn't trigger, stop the agent from the web UI or restart the server
3. Provide more specific instructions
4. Try a different model

### Agent not using the right tool

**Symptom:** Agent uses `bash` when it should use `str_replace_editor`

**Fix:** Be explicit in your instructions:
```
Edit the function `calculate_total` in src/utils.py to add error handling
for empty lists. Use the file editor, not bash commands.
```

### Agent spending too much

**Symptom:** Cost exceeds expectations

**Fix:**
```toml
[core]
max_budget_per_task = 2.0    # Lower the cap

[llm]
model = "claude-haiku-4-5-20251001" # Use cheaper model
caching_prompt = true         # Enable prompt caching
```

### Circuit breaker tripping too early

**Symptom:** Agent pauses with "Circuit breaker tripped"

**Fix:** This is a safety feature. To investigate:
1. Check what errors triggered it
2. Fix the underlying issue (e.g., file permissions)
3. Resume the conversation with more context

To adjust thresholds (not recommended for production):
```toml
[agent]
enable_circuit_breaker = true   # Keep enabled
```

### Task finishes without completing

**Symptom:** Agent declares completion but work is incomplete

**Fix:**
1. Be more specific about success criteria
2. Ask the agent to verify its work before finishing
3. Use the task tracker tool for multi-step tasks

---

## Runtime Issues

### Command timeout

**Symptom:** `Command timed out after X seconds`

**Fix:**
```toml
[runtime]
timeout = 300   # Increase from default 120
```

### File permission errors

**Symptom:** `PermissionError: [Errno 13]` or `Access denied`

**Fix:**
1. Ensure the workspace directory is writable
2. On Windows, close any editors/IDEs locking files
3. Run as administrator if needed (not recommended generally)

### Workspace directory issues

**Symptom:** Files not found or created in wrong location

**Fix:** Check the workspace path in your config or specify it:
```bash
python start_server.py --workspace /path/to/your/project
```

---

## Web UI Issues

### Browser shows connection refused

**Symptom:** `Connection refused` or blank page at `http://localhost:3000`

**Fix:**
1. Ensure the backend is running: `python start_server.py` or `uv run app serve`
2. Use the same host/port printed in the server logs (default **3000**)
3. Verify no firewall is blocking localhost

### Page loads but Socket.IO disconnects

**Fix:**
1. Check browser devtools → Network for WebSocket errors
2. Confirm you are not mixing `http`/`https` or wrong origin with reverse proxies

---

## Performance Issues

### Slow LLM responses

**Symptom:** Agent takes long pauses between actions

**Causes and fixes:**
1. **Network latency**: Use Ollama for local models
2. **Large context**: Enable condensation (`type = "smart"`)
3. **Complex model**: Use a faster model for simple tasks
4. **Rate limiting**: Increase retry wait times

### High memory usage

**Symptom:** Process memory grows over time

**Fix:**
1. Enable condensation to limit history size
2. Close old conversations
3. Reduce `max_message_chars`

### Slow startup

**Symptom:** Server takes a long time to start

**Causes:**
- Plugin initialization
- Model catalog loading
- Database connections

**Fix:**
```toml
[core]
enable_browser = false   # Disable if not needed
```

---

## Windows-Specific Issues

### Path separator issues

**Symptom:** File paths with backslashes cause errors

**Fix:** App normalizes paths internally. If you see path issues:
1. Use forward slashes in config: `workspace = "C:/Users/me/project"`
2. Report the issue — path normalization should handle this

### Long path names

**Symptom:** `FileNotFoundError` for deeply nested files

**Fix:** Enable long paths on Windows:
```powershell
# Run as Administrator
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
  -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

### PermissionError on workspace cleanup

**Symptom:** `PermissionError` when closing a session

**Cause:** Windows file handle locking. App retries cleanup automatically.

**Fix:** Close any editors or file explorers accessing the workspace directory.

### Shell detection

**Symptom:** Commands fail with shell-related errors

**Fix:** App auto-detects the shell. Verify PowerShell is available:
```powershell
$PSVersionTable.PSVersion   # Should be 5.1+
```

---

## Diagnostic Commands

### Check system health

```bash
# Verify Python and dependencies
python --version
uv --version

# Verify Git
git --version

# Check if server starts
python start_server.py --help

# Run tests
uv run pytest backend/tests/unit/ --tb=short -q
```

### Check server status

```bash
# API health check
curl http://localhost:3000/api/health

# Check API docs
# Open http://localhost:3000/docs in browser
```

### Check logs

```bash
# Backend logs are printed to stdout by default.
# For verbose logging:
LOG_LEVEL=DEBUG python start_server.py
```

### Reset to defaults

```bash
# Reset config
cp config.template.toml config.toml

# Clear cache
rm -rf /tmp/cache /tmp/file_store

# Reset dependencies
uv lock
uv sync
```

---

## Getting Help

If none of the above resolves your issue:

1. **Search** [GitHub Issues](https://github.com/josephsenior/App/issues)
2. **Open** a new issue with:
   - Steps to reproduce
   - Expected vs actual behavior
   - Output of `python --version` and `uv --version`
   - Relevant log output
   - Operating system and version
3. **Ask** in [GitHub Discussions](https://github.com/josephsenior/App/discussions)
