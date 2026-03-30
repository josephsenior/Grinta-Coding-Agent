# LLM Integration System

## Overview

App's LLM system provides a robust, provider-agnostic abstraction layer using direct SDK clients for major providers (OpenAI, Anthropic, Google Gemini, and xAI Grok). This approach ensures maximum stability, performance, and access to the latest provider-specific features.

## Key Features

- ✅ **Direct SDK Support** - Native clients for OpenAI, Anthropic, Gemini, and Grok
- ✅ **Secure API Key Management** - Auto-detection, format validation
- ✅ **Feature Detection** - Function calling, caching, vision support
- ✅ **Cost Tracking** - Real-time cost monitoring per model
- ✅ **Retry Logic** - Exponential backoff for reliability
- ✅ **Streaming Support** - Real-time token streaming
- ✅ **Prompt Caching** - Support for provider-specific caching features

## Architecture

### Provider Auto-Resolver Pattern

App uses an intelligent routing system that automatically detects providers and discovers local endpoints:

```
User specifies model: "ollama/qwen2.5-coder" (canonical id)
   ↓
ProviderResolver detects provider: "ollama"
   ↓
ProviderResolver discovers local endpoint: "http://localhost:11434"
   ↓
DirectLLMClient (OpenAI-compatible) initialized
   ↓
SDK.completion(model="qwen2.5-coder", ...)  # Prefix stripped
   ↓
Response + cost tracking + metrics
```

### New Components (Provider Auto-Resolver)

1. **ProviderResolver** (`provider_resolver.py`)
   - Auto-detects provider from model names
   - Discovers local endpoints (Ollama, LM Studio, vLLM)
   - Resolves base URLs with intelligent priority
   - Strips provider prefixes for API calls

2. **Local Endpoint Discovery**
   - Auto-probes Ollama (`:11434`), LM Studio (`:1234`), vLLM (`:8000`)
   - Environment variable override support
   - No manual configuration needed for standard setups

## Core Components

### 1. LLM Class (`llm.py`)

Main interface for LLM calls:

```python
from app.models import LLM
from app.core.config import LLMConfig

# Create LLM instance
config = LLMConfig(
    model="claude-sonnet-4-20250514",
    api_key="sk-ant-...",
    temperature=0.0,
    max_output_tokens=8000
)
llm = LLM(config=config, service_id="main")

# Make completion call
response = llm.completion(
    messages=[{"role": "user", "content": "Hello"}],
    tools=[...]  # Optional function calling
)
```

**Features:**
- Retry logic with exponential backoff
- Cost calculation and tracking
- Streaming support
- Function calling (when supported)
- Vision support (when supported)
- Prompt caching (when supported)
- **Auto-discovery of local endpoints** (NEW)

### 1.5 Working with Local Models

**Auto-Discovery:**
```python
from backend.inference import LLM

# No base_url needed - auto-discovers Ollama
llm = LLM(model="ollama/llama3.2")

# Or LM Studio
llm = LLM(model="lmstudio/qwen2.5-coder")

# Or vLLM
llm = LLM(model="vllm/mistral-7b")
```

**Discover Available Models:**
```bash
# Find all local models
python -m backend.inference.discover_models

# Output:
# 📦 OLLAMA
#    - llama3.2
#    - qwen2.5-coder
#    - mistral
```

**Check Provider Status:**
```bash
python -m backend.inference.discover_models status

# Output:
# ✓ OLLAMA          RUNNING
# ✗ LM STUDIO       NOT FOUND
# ✗ VLLM            NOT FOUND
```

### 2. API Key Manager (`api_key_manager.py`)

Secure multi-provider API key management:

```python
from app.core.config.api_key_manager import api_key_manager

# Get correct API key for model
key = api_key_manager.get_api_key_for_model(
    model="openrouter/gpt-4o",
    provided_key=None  # Falls back to environment
)

# Set environment variables
api_key_manager.set_environment_variables(
    model="gpt-4o",
    api_key=key
)
```

**Features:**
- Provider auto-detection from model string
- API key format validation (prefix matching)
- Environment variable fallbacks
- Secure storage (Pydantic SecretStr)

### 3. Provider Configuration (`provider_config.py`)

Pre-configured settings for 30+ providers:

```python
from app.core.config.provider_config import provider_config_manager

# Get provider config
config = provider_config_manager.get_provider_config("anthropic")

# Validate parameters
cleaned = provider_config_manager.validate_and_clean_params(
    provider="anthropic",
    params={"model": "claude-4", "api_key": "...", "base_url": "..."}
)
# Returns: params with forbidden parameters removed
```

**Each Provider Config Includes:**
- Environment variable name
- Required parameters
- Optional parameters
- Forbidden parameters
- API key prefix validation
- Streaming support flag
- Protocol requirements

### 4. Model Features (`model_features.py`)

Automatic feature detection:

```python
from app.models.model_features import get_features

features = get_features("claude-haiku-4-5-20251001")

# Check capabilities
if features.supports_function_calling:
    # Use native function calling
if features.supports_prompt_cache:
    # Enable caching for cost savings
if features.supports_reasoning_effort:
    # Use extended thinking
```

**Supported Features:**
- Function calling (tools/actions)
- Reasoning effort (o1, o3, Gemini 2.5)
- Prompt caching (Claude 3.5+, 4, 4.5)
- Stop words support

## Supported Providers

### Major Providers

| Provider | Models | API Key Env Var | Key Prefix |
|----------|--------|-----------------|------------|
| Anthropic | Claude 3.5, 4, 4.5 | `ANTHROPIC_API_KEY` | `sk-ant-` |
| OpenAI | GPT-4, GPT-5, o3, o4-mini | `OPENAI_API_KEY` | `sk-` |
| OpenRouter | 200+ models (meta-provider) | `OPENROUTER_API_KEY` | `sk-or-` |
| xAI | Grok 4, Grok 4 Fast | `XAI_API_KEY` | - |
| Google | Gemini 2.5 Pro, Flash | `GEMINI_API_KEY` | `AIza` |
| Mistral | Devstral series | `MISTRAL_API_KEY` | `mistral-` |
| Groq | Fast inference | `GROQ_API_KEY` | `gsk_` |

### Enterprise Providers

| Provider | Use Case | Setup |
|----------|----------|-------|
| AWS Bedrock | Enterprise, compliance | AWS credentials |
| Azure OpenAI | Enterprise, compliance | Azure subscription |
| Google Vertex AI | Enterprise, GCP | GCP credentials |

### Self-Hosted / Local (Auto-Discovery)

| Provider | Default Port | Auto-Discovery | Use Case |
|----------|-------------|----------------|----------|
| Ollama | 11434 | ✓ | Local inference, privacy |
| LM Studio | 1234 | ✓ | GUI-based local models |
| vLLM | 8000 | ✓ | Production local deployment |

**No configuration needed** - App automatically discovers running local providers:

```python
# Just specify the model
llm = LLM(model="ollama/llama3.2")
# App automatically:
# 1. Detects provider is "ollama"
# 2. Probes localhost:11434
# 3. Verifies it's a valid LLM endpoint
# 4. Uses it automatically
```

**Override auto-discovery:**
```bash
# Custom Ollama location
export OLLAMA_HOST="http://192.168.1.100:11434"

# Custom LM Studio
export LM_STUDIO_BASE_URL="http://localhost:1234/v1"

# Custom vLLM
export VLLM_BASE_URL="http://localhost:8000/v1"
```

## Configuration

### Base URL Resolution Priority

When determining where to send API requests, App uses this priority order:

1. **Explicit** - Passed directly in code: `LLM(base_url="http://custom:9000")`
2. **Environment** - Provider-specific env vars (e.g., `OLLAMA_HOST`)
3. **Auto-Discovery** - Probes common local ports (`:11434`, `:1234`, `:8000`)
4. **Defaults** - Cloud provider defaults (e.g., `https://api.openai.com/v1`)

```python
# Priority 1: Explicit (highest)
llm = LLM(model="ollama/llama3.2", base_url="http://gpu-server:11434")

# Priority 2: Environment variable
os.environ["OLLAMA_HOST"] = "http://192.168.1.100:11434"
llm = LLM(model="ollama/llama3.2")

# Priority 3: Auto-discovery
# (App automatically probes localhost:11434)
llm = LLM(model="ollama/llama3.2")

# Priority 4: Default (for cloud providers)
llm = LLM(model="gpt-4")  # → https://api.openai.com/v1
```

### Via config.toml

```toml
[llm]
model = "claude-sonnet-4-20250514"
api_key = "sk-ant-..."
temperature = 0.0
max_output_tokens = 8000

# Retry configuration
num_retries = 5
retry_min_wait = 8
retry_max_wait = 64
retry_multiplier = 8

# Features
caching_prompt = true      # Enable prompt caching (Claude)
disable_vision = false     # Enable vision for images
native_tool_calling = true # Use native function calling

# Cost control
max_message_chars = 30000  # Truncate long messages

```

### Via Environment Variables

```bash
# Model selection
LLM_MODEL=claude-sonnet-4-20250514

# API keys (cloud providers)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
OPENROUTER_API_KEY=sk-or-...
XAI_API_KEY=...
GEMINI_API_KEY=AIza...

# Local provider endpoints (NEW)
OLLAMA_HOST=http://localhost:11434
LM_STUDIO_BASE_URL=http://localhost:1234/v1
VLLM_BASE_URL=http://localhost:8000/v1

# Advanced
LLM_BASE_URL=http://custom-llm-proxy:8000
LLM_API_VERSION=2024-12-01
```

## Adding a New Provider

### Step 1: Add Provider Config

Edit `App/core/config/provider_config.py`:

```python
configs['newprovider'] = ProviderConfig(
    name='newprovider',
    env_var='NEWPROVIDER_API_KEY',
    requires_protocol=True,
    supports_streaming=True,
    required_params={'api_key', 'model'},
    optional_params={'timeout', 'temperature'},
    forbidden_params={'custom_llm_provider'},
    api_key_prefixes=['np-'],
    api_key_min_length=20,
)
```

### Step 2: Add Feature Patterns (if needed)

Edit `App/llm/model_features.py`:

```python
FUNCTION_CALLING_PATTERNS: list[str] = [
    # ... existing patterns
    "newprovider/*",  # All newprovider models support function calling
]
```

### Step 3: Test

```python
from app.models import LLM
from app.core.config import LLMConfig

config = LLMConfig(
    model="newprovider/model-name",
    api_key="np-your-key"
)
llm = LLM(config=config, service_id="test")

response = llm.completion(
    messages=[{"role": "user", "content": "Hello"}]
)
```

## Cost Tracking

### Automatic Cost Calculation

```python
# Cost is automatically tracked in metrics
llm.metrics.accumulated_cost  # Total cost in USD
llm.metrics.total_tokens      # Total tokens
```

### Per-Request Cost

```python
response = llm.completion(messages=[...])

# Cost logged automatically:
# "Cost: 0.05 USD | Accumulated Cost: 2.34 USD"
```

### Custom Cost Overrides

```toml
[llm]
input_cost_per_token = 0.001   # Override default costs
output_cost_per_token = 0.003
```

## Advanced Features

### Prompt Caching (Claude Models)

**Supported:**
- Claude 3.5 Sonnet
- Claude 3.5 Haiku
- Claude 4 Sonnet
- Claude 4.5 Haiku
- Claude 4.5 Sonnet

**How it works:**
```python
# Enable caching
config = LLMConfig(
    model="claude-sonnet-4-20250514",
    caching_prompt=True  # Enable caching
)

# First call: Full cost
response1 = llm.completion(messages=[...])  # Cost: $0.05

# Second call with same prefix: Reduced cost
response2 = llm.completion(messages=[...])  # Cost: $0.01 (80% savings!)
```

**Benefits:**
- 35-50% cost reduction
- Faster responses (cached tokens processed faster)
- Automatic provider-specific optimizations

### Function Calling

**Supported models:** GPT-4, Claude 3.5+, Gemini 2.0+, etc.

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"}
                }
            }
        }
    }
]

response = llm.completion(
    messages=[...],
    tools=tools,
    tool_choice="auto"
)

# Parse tool calls
if response.choices[0].message.tool_calls:
    for tool_call in response.choices[0].message.tool_calls:
        # Execute tool
        pass
```

### Vision Support

**Supported models:** GPT-4o, Claude 3.5+, Gemini 2.0+

```python
from app.core.message import Message

# Image message
message = Message(
    role="user",
    content=[
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    ]
)

response = llm.completion(messages=[message])
```

### Streaming

```python
# Enable streaming
response = llm.completion(
    messages=[...],
    stream=True
)

# Process chunks
for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

## Metrics

### LLM Metrics Class

```python
from app.models.metrics import Metrics

metrics = Metrics(model_name="claude-4")

# Track usage
metrics.add_token_usage(
    prompt_tokens=1000,
    completion_tokens=500,
    cache_read_tokens=200  # From prompt cache
)

# Track cost
metrics.add_cost(0.05)  # $0.05

# Track latency
metrics.add_response_latency(
    latency=0.85,  # 850ms
    prompt_tokens=1000,
    completion_tokens=500
)

# Get stats
print(f"Total cost: ${metrics.accumulated_cost}")
print(f"Avg latency: {metrics.avg_response_latency}s")
```

## Troubleshooting

### "Ollama not detected" / "Local provider not found"

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# If not, start it
ollama serve

# Or explicitly set the endpoint
export OLLAMA_HOST="http://localhost:11434"

# Check provider status
python -m backend.inference.discover_models status
```

### "No API key found"

```bash
# Check environment variable
echo $ANTHROPIC_API_KEY

# Set in .env
ANTHROPIC_API_KEY=sk-ant-...

# Restart application
```

### "Model not found"

```bash
# List available models
curl http://localhost:3000/api/options/models

# Check model name format:
# Correct: "claude-sonnet-4-20250514"
# Correct: "openrouter/anthropic/claude-3.5-sonnet"
# Wrong: "claude-sonnet-4" (missing date)
```

### "Rate limit exceeded"

```bash
# Check LLM provider rate limits
# Solution: Wait or switch to different model

# Or use cheaper model with higher limits
LLM_MODEL=gpt-4o-mini
```

### "Function calling not working"

```python
# Check if model supports function calling
from app.models.model_features import get_features

features = get_features(your_model)
print(f"Function calling: {features.supports_function_calling}")

# If False: Use mock function calling (automatic fallback)
```

## Best Practices

### 0. Leverage Local Models for Development

**Use local models to:**
- Reduce API costs during development
- Work offline
- Increase iteration speed

```bash
# Start Ollama
ollama serve

# Pull coding-optimized model
ollama pull qwen2.5-coder

```

```python
# Point LLM config at a local model id, e.g. ollama/qwen2.5-coder
```

### 1. Choose the Right Model

**For speed:**
- `claude-haiku-4-5-20251001` - 2x faster than Sonnet
- `gpt-4o-mini` - Fast and cheap
- `openrouter/x-ai/grok-code-fast-1` - 2x faster, very cheap

**For quality:**
- `claude-sonnet-4-5-20250929` - Best for coding
- `gpt-5-2025-08-07` - Frontier model
- `o3-mini` - Best reasoning

**For cost:**
- `gpt-4o-mini` - $0.15/$0.60 per 1M tokens
- `claude-haiku-4-5-20251001` - $1/$5 per 1M tokens
- `openrouter/x-ai/grok-code-fast-1` - $0.20/$0.50 per 1M tokens

### 2. Enable Caching

```toml
[llm]
model = "claude-sonnet-4-20250514"
caching_prompt = true  # 35-50% cost savings
```

### 3. Monitor Costs

```bash
# Check accumulated costs
tail -f logs/App.log | grep "Accumulated Cost"

# Or via Grafana
open http://localhost:3001/grafana
```

### 4. Handle Errors Gracefully

```python
try:
    response = llm.completion(messages=[...])
except RateLimitError:
    # Wait and retry
    time.sleep(60)
except APIConnectionError:
    # Switch to fallback model
    llm.config.model = "gpt-4o-mini"
```

## Provider-Specific Notes

### Anthropic (Claude)

**Prompt Caching:**
- Automatically enabled for Claude 3.5+, 4, 4.5
- Reduces costs significantly for long conversations
- No code changes needed

**Extended Thinking:**
- Claude Opus 4.1 supports extended thinking
- Automatically disabled in config

### OpenRouter

**Access 200+ Models:**
- Single API key for all models
- Automatic fallback if model unavailable
- Free models available (see `openrouter/meta-llama/llama-3.3-70b-instruct:free`)

**Rate Limits:**
- Vary by model
- Free models: Lower limits
- Paid models: Higher limits

### xAI (Grok)

**Grok 4 Fast:**
- 2M token context window
- 98% cheaper than Grok 4
- Optimized for tool use
- Perfect for high-volume tasks

**Access:**
```bash
# Via OpenRouter
LLM_MODEL=openrouter/x-ai/grok-code-fast-1
OPENROUTER_API_KEY=sk-or-...

# Or direct xAI API
XAI_API_KEY=...
```

### Ollama (Local)

**Run models locally:**

```bash
# Start Ollama
ollama serve

# Pull model
ollama pull llama3.3:70b

# Configure App
LLM_MODEL=ollama/llama3.3:70b
OLLAMA_BASE_URL=http://localhost:11434
```

**Benefits:**
- Free (no API costs)
- Privacy (runs locally)
- Fast (no network latency)

**Trade-offs:**
- Requires GPU for good performance
- Limited to smaller models (70B max typically)
- Lower quality than frontier models

## File Reference

| File | Purpose |
|------|---------|
| `llm.py` | Main LLM class, completion wrapper |
| `async_llm.py` | Async LLM wrapper |
| `streaming_llm.py` | Streaming support |
| `retry_mixin.py` | Retry logic |
| `debug_mixin.py` | Debug logging |
| `metrics.py` | Cost and latency tracking |
| `model_features.py` | Feature detection |
| `fn_call_converter.py` | Mock function calling fallback |
| `bedrock.py` | AWS Bedrock support |
| `llm_utils.py` | Utility functions |
| `llm_registry.py` | Model registry |
| **`provider_resolver.py`** | **Provider detection & local discovery (NEW)** |
| **`catalog_loader.py`** | **Model catalog & metadata (NEW)** |
| **`discover_models.py`** | **CLI tool for local model discovery (NEW)** |

## Examples

See `docs/examples/02_custom_provider.py` for complete example of adding a new provider.

## References

- [Architecture](../../docs/ARCHITECTURE.md) - System overview
- [API Reference](../../docs/API_REFERENCE.md) - API documentation
