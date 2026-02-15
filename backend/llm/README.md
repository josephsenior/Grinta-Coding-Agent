# LLM Integration System

## Overview

Forge's LLM system provides a robust, provider-agnostic abstraction layer using direct SDK clients for major providers (OpenAI, Anthropic, Google Gemini, and xAI Grok). This approach ensures maximum stability, performance, and access to the latest provider-specific features.

## Key Features

- ✅ **Direct SDK Support** - Native clients for OpenAI, Anthropic, Gemini, and Grok
- ✅ **Secure API Key Management** - Auto-detection, format validation
- ✅ **Feature Detection** - Function calling, caching, vision support
- ✅ **Cost Tracking** - Real-time cost monitoring per model
- ✅ **Retry Logic** - Exponential backoff for reliability
- ✅ **Streaming Support** - Real-time token streaming
- ✅ **Prompt Caching** - Support for provider-specific caching features

## Architecture

```
User selects model: "gpt-4o"
   ↓
APIKeyManager extracts provider: "openai"
   ↓
ProviderConfigManager validates parameters
   ↓
DirectLLMClient (OpenAIClient) initialized
   ↓
SDK.completion(model="gpt-4o", ...)
   ↓
Response + cost tracking + metrics
```

## Core Components

### 1. LLM Class (`llm.py`)

Main interface for LLM calls:

```python
from forge.models import LLM
from forge.core.config import LLMConfig

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

### 2. API Key Manager (`api_key_manager.py`)

Secure multi-provider API key management:

```python
from forge.core.config.api_key_manager import api_key_manager

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
from forge.core.config.provider_config import provider_config_manager

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
from forge.models.model_features import get_features

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

### Self-Hosted

| Provider | Use Case | Setup |
|----------|----------|-------|
| Ollama | Local, privacy | Local Ollama server |

## Configuration

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

# API keys
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
OPENROUTER_API_KEY=sk-or-...
XAI_API_KEY=...
GEMINI_API_KEY=AIza...

# Advanced
LLM_BASE_URL=http://custom-llm-proxy:8000
LLM_API_VERSION=2024-12-01
```

## Adding a New Provider

### Step 1: Add Provider Config

Edit `Forge/core/config/provider_config.py`:

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

Edit `Forge/llm/model_features.py`:

```python
FUNCTION_CALLING_PATTERNS: list[str] = [
    # ... existing patterns
    "newprovider/*",  # All newprovider models support function calling
]
```

### Step 3: Test

```python
from forge.models import LLM
from forge.core.config import LLMConfig

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
from forge.core.message import Message

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
from forge.models.metrics import Metrics

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
from forge.models.model_features import get_features

features = get_features(your_model)
print(f"Function calling: {features.supports_function_calling}")

# If False: Use mock function calling (automatic fallback)
```

## Best Practices

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
tail -f logs/Forge.log | grep "Accumulated Cost"

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

# Configure Forge
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

## Examples

See `docs/examples/02_custom_provider.py` for complete example of adding a new provider.

## References

- [Architecture](../../docs/ARCHITECTURE.md) - System overview
- [API Reference](../../docs/API_REFERENCE.md) - API documentation
