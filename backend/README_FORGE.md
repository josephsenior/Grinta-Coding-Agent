# Forge Architecture

This directory contains the core components of Forge.

This diagram provides an overview of the roles of each component and how they communicate and collaborate.
![Forge System Architecture Diagram (July 4, 2024)](../docs/static/img/system_architecture_overview.png)

## Classes

The key classes in Forge are:

- LLM: brokers all interactions with large language models. Works with any underlying completion model using direct SDK clients.
- Agent: responsible for looking at the current State, and producing an Action that moves one step closer toward the end-goal.
- AgentController: initializes the Agent, manages State, and drive the main loop that pushes the Agent forward, step by step
- State: represents the current state of the Agent's task. Includes things like the current step, a history of recent events, the Agent's long-term plan, etc
- EventStream: a central hub for Events, where any component can publish Events, or listen for Events published by other components
  - Event: an Action or Observeration
    - Action: represents a request to e.g. edit a file, run a command, or send a message
    - Observation: represents information collected from the environment, e.g. file contents or command output
- Runtime: responsible for performing Actions, and sending back Observations
  - Runtime Environment: the part of the runtime responsible for running commands in an isolated local workspace
- Server: brokers Forge sessions over HTTP/WebSocket (web UI and API clients)
  - Session: holds a single EventStream, a single AgentController, and a single Runtime. Generally represents a single task (but potentially including several user prompts)
  - ConversationManager: keeps a list of active sessions, and ensures requests are routed to the correct Session

## Control Flow

Here's the basic loop (in pseudocode) that drives agents.

```python
while True:
  prompt = agent.generate_prompt(state)
  response = llm.completion(prompt)
  action = agent.parse_response(response)
  observation = runtime.run(action)
  state = state.update(action, observation)
```

In reality, most of this is achieved through message passing, via the EventStream.
The EventStream serves as the backbone for all communication in Forge.

```mermaid
flowchart LR
  Agent--Actions-->AgentController
  AgentController--State-->Agent
  AgentController--Actions-->EventStream
  EventStream--Observations-->AgentController
  Runtime--Observations-->EventStream
  EventStream--Actions-->Runtime
  Clients--Actions-->EventStream
```

## Runtime

Please refer to the [documentation](https://docs.forge.dev/usage/architecture/runtime) to learn more about `Runtime`.
