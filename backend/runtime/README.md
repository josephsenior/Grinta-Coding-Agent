# Forge Runtime

## Introduction

The Forge Runtime folder contains the core components responsible for executing actions and managing the runtime environment for the Forge project. This README provides an overview of the main components and their interactions.

## Main Components

### 1. base.py

The `base.py` file defines the `Runtime` class, which serves as the primary [interface](./base.py) for agent interactions with the external environment. It handles various operations including:

- Bash execution
- Browser interactions
- Filesystem operations
- Environment variable management
- Plugin management

### 2. impl/local/local_runtime_inprocess.py

The `local_runtime_inprocess.py` file contains the `LocalRuntime` class (aliased as `LocalRuntimeInProcess`), which implements the Runtime interface.

This implementation runs the `ActionExecutor` directly in the same process as the Forge backend, eliminating the overhead of subprocesses or HTTP communication. It is designed for desktop applications and local development.

### 3. action_execution_server.py

The `action_execution_server.py` file contains the `ActionExecutor` class, which is responsible for executing actions directly.

Key features of the `ActionExecutor` class:

- Initialization of user environment and bash shell
- Plugin management and initialization
- Execution of various action types (bash commands, file operations, browsing)
- Integration with Playwright for web interactions

## Workflow Description

1. **Initialization**:
   - The `Runtime` is initialized with configuration and event stream.
   - Environment variables are set up using `ainit` method.
   - Plugins are loaded and initialized.

2. **Action Handling**:
   - The `Runtime` receives actions through the event stream.
   - Actions are validated and routed to appropriate execution methods.

3. **Action Execution**:
   - Different types of actions are executed:
     - Bash commands using `run` method
     - File operations (read/write) using `read` and `write` methods
   - Web browsing via external MCP tools (e.g., browser-use)

4. **Observation Generation**:
   - After action execution, corresponding observations are generated.
   - Observations are added to the event stream.

5. **Plugin Integration**:
   - Plugins like AgentSkills are initialized and integrated into the runtime.

## Runtime Type

### Local Runtime (In-Process)

The Local Runtime is the primary and only supported runtime in this architecture:

- Runs ActionExecutor directly in-process
- No container or subprocess overhead
- Direct access to local system resources
- Fastest execution speed
- Simplified architecture

**Important: This runtime provides no isolation as it runs directly on the host machine. All actions are executed with the same permissions as the user running Forge.**

## Related Components

- The runtime interacts closely with the event system defined in the `forge.events` module.
- It relies on configuration classes from `forge.core.config`.
- Logging is handled through `forge.core.logger`.
