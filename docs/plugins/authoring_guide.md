# App Plugin Authoring Guide

App supports a lightweight, hook-based plugin system that allows you to extend the agent's behavior, inspect events, and modify actions.

## 1. Plugin Structure

A App plugin is a Python package that exposes a `app.plugins` entry point.

### Minimal Example

```python
from backend.core.plugin import AppPlugin, PluginRegistry

class MyPlugin(AppPlugin):
    name = "my-plugin"
    version = "0.1.0"
    
    async def on_action_pre(self, action):
        print(f"Executing action: {action}")
        return action

def register(registry: PluginRegistry):
    registry.register(MyPlugin())
```

### pyproject.toml

```toml
[project.entry-points."app.plugins"]
my_plugin = "my_package:register"
```

## 2. Available Hooks

Inherit from `AppPlugin` and override these methods:

### Action Hooks

- `async def on_action_pre(self, action: Action) -> Action`
  - Called before an action is executed.
  - Return the action (modified if desired).
  - Raise exception to block execution.

- `async def on_action_post(self, action: Action, observation: Observation) -> Observation`
  - Called after execution.
  - Return the observation (modified if desired).

### Event Hooks

- `async def on_event(self, event: Event) -> None`
  - Called for every event emitted to the stream.
  - Useful for logging or side-effects.

### Session Hooks

- `async def on_session_start(self, session_id: str, metadata: dict) -> None`
- `async def on_session_end(self, session_id: str, metadata: dict) -> None`

### LLM Hooks

- `async def on_llm_pre(self, messages: list, **kwargs) -> list`
  - Inspect or modify LLM messages before sending.
- `async def on_llm_post(self, response: Any) -> Any`
  - Inspect LLM response.

## 3. Best Practices

- **Async**: All hooks are async. Avoid blocking code.
- **Error Handling**: Exceptions in hooks are logged but generally suppress the plugin; critical errors might disrupt the agent if not handled.
- **State**: Plugins are singletons in the registry. Store session-specific state carefully (keyed by session_id).
