# Grinta Runtime

## Introduction

This folder contains the components responsible for executing actions and managing the local runtime environment for Grinta. This README summarizes the main modules and how they fit together.

## Main Components

### 1. base.py

The `base.py` file defines the `Runtime` class, which serves as the primary [interface](./base.py) for agent interactions with the external environment. It handles various operations including:

- Bash execution
- Browser interactions
- Filesystem operations
- Environment variable management
- Plugin management

### 2. drivers/local/local_runtime_inprocess.py

The `local_runtime_inprocess.py` module defines `LocalRuntime` (aliased as `LocalRuntimeInProcess`), which implements the `Runtime` interface.

This implementation runs the runtime executor (`RuntimeExecutor`) in the same process as the CLI/orchestrator, avoiding subprocess or HTTP hops to the executor. It is the default path for local development and installed CLI use.

### 3. action_execution_server.py

The `action_execution_server.py` file contains the runtime executor class (`RuntimeExecutor`), which is responsible for executing actions directly.

Key features of the runtime executor:

- Initialization of user environment and bash shell
- Plugin management and initialization
- Execution of various action types (bash commands, file operations, browsing)
- Web interactions via external MCP tools

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

- Runs the runtime executor directly in-process
- No container or subprocess overhead
- Direct access to local system resources
- Fastest execution speed
- Simplified architecture

**Important: this runtime does not isolate the host. Actions run with the same permissions as the user running Grinta.**

Grinta also supports a `hardened_local` execution profile. This adds stricter local policy enforcement for workspace-scoped commands, file access, sensitive paths, network-capable commands, package installs, background processes, and interactive terminal behavior. It improves local safety, but it is still not sandboxing or host isolation.

The optional `sandboxed_local` profile reuses those policy gates and adds
OS-native process isolation for supported **non-interactive** subprocess
commands. It uses `bwrap` on Linux, AppContainer on Windows, and `sandbox-exec`
on macOS when the platform backend is available. Interactive PTY sessions remain
outside that boundary, so this profile is not complete host isolation.

## Related Components

- The runtime interacts closely with the ledger defined in `backend.ledger`.
- It relies on configuration from `backend.core.config`.
- Logging uses the shared backend logging setup under `backend.core`.
