# 06. The System Design Playbook

A lot of people hear "coding agent" and assume the hard part is the model.

That is only part of the story.

The harder part is the system around the model.

Grinta is not just a set of prompts attached to tools. It is a software system with choices about API shape, transport, configuration, storage, parsing, safety, extensibility, runtime policy, and platform support. Many of the decisions I am proudest of are not purely agentic decisions at all. They are system-design decisions.

This chapter is about those choices and why they matter.

It is personal to me in a quieter way than the other chapters. Models are the glamorous part of this field. The decisions in this chapter are the ones that made me feel like I was doing real engineering, not building prompt theater.

---

## Model-Agnostic Was a Principle, Not a Checkbox

This is one of the strongest convictions in the entire project.

I never wanted Grinta to become a product that only made sense if you used one provider's model.

Why would I build a coding agent that only works well with Claude if I am not even building inside Claude's ecosystem myself? Why would I accept a design that forces users into one vendor when the entire point of good engineering is to preserve freedom where possible?

That is why Grinta is model-agnostic by philosophy, not just by feature list.

I felt stubborn about this early, and I am glad I did. I have too much respect for users to design a tool that secretly becomes a trap the moment one provider changes pricing, quality, or priorities.

### What That Means in Practice

The inference layer was built to support multiple providers and local runtimes instead of assuming one blessed path. That includes cloud providers and local endpoints, with automatic resolution and discovery behavior around common local setups.

The practical result is that Grinta can work with:

- Anthropic-style models
- OpenAI-style models
- Gemini-style models
- local endpoints such as Ollama and other OpenAI-compatible servers

Under the hood, this is not one generic wrapper pretending all providers are identical. Grinta has three direct client families — one for OpenAI-compatible APIs, one for native Anthropic, and one for native Google — because each provider has real differences in how they handle tool calling, streaming, and response structure. Above those sits a provider resolver that knows about eighteen provider prefixes and can probe common local endpoints automatically. Model metadata lives in a catalog file so adding support for a new model is often a data change instead of a code change. And for models that do not support native tool calling, there is even a fallback converter that turns tool invocations into a text-based contract.

That last detail matters more than it sounds. I built it because I did not want local models with no function-calling support to be second-class citizens. If you are running an open-source model through Ollama and it cannot do native tool calls, the system should still work — just through a different encoding. That felt like a matter of principle.

### Why This Matters

This matters for several reasons.

#### 1. Cost flexibility

Different users have different budgets.
A system that only makes sense with the most expensive model is strategically weak.

#### 2. Platform independence

No single provider should define the identity of the tool.

#### 3. Future resilience

Model quality shifts. APIs change. Pricing changes. Vendors come and go. A model-agnostic design ages better.

#### 4. Product honesty

The tool should adapt to the user, not the user to the tool.

This is one of the deepest ways Grinta diverges from more vendor-shaped agent products.

---

## FastAPI + Socket.IO: Because Agents Are Not Simple HTTP Forms

A normal CRUD application can get away with pure request/response thinking.
An autonomous agent usually cannot.

Agents do not just return a final answer. They:

- stream thinking and progress
- execute tools
- wait on observations
- recover from failures
- update plans over time
- expose long-running state transitions

That is why the transport layer matters.

### Why FastAPI

FastAPI was a strong fit because it provides:

- a clean Python-native web stack
- strong typing and schema friendliness
- a practical path for HTTP APIs and local server flows
- an ecosystem that works well with the rest of the architecture

It is fast enough, pragmatic enough, and does not overcomplicate the backend.

### Why Socket.IO

Socket.IO stayed relevant because real agent UX benefits from stateful live communication.

Even after the pivot away from the heavier SaaS identity, the need for live updates did not magically disappear. If you have ever watched an agent work in real time, you understand why a richer event channel matters.

This is one of the design choices that came from the frontend and platform phase of the project. It is not accidental leftover tech. It reflects the reality that agent systems are dynamic.

That is also why the transport layer grew real operational features instead of staying a toy websocket wrapper. `EventStream` has typed subscriber roles, backpressure management, optional event coalescing, secret masking, and persistence hooks. Once you accept that the agent is a live system instead of a single response, those details stop looking like overengineering.

---

## Local-First Storage and the Right Kind of Persistence

A local-first product should feel local all the way down.

That sounds obvious, but it has consequences.

The current Grinta storage story centers around project-scoped local persistence under `.grinta/storage/`. That gives the system a canonical local root for sessions, storage artifacts, and related data instead of scattering state across random legacy paths.

This matters because consistency in storage is not just neatness. It affects:

- session recovery
- portability of local project state
- debuggability

---

## The Dividing Line: Native Tools vs. MCP Servers

When building an autonomous coding agent, deciding *how* the agent interacts with the world is the most important architectural choice you can make. Do you build everything yourself? Do you rely on an ecosystem like the Model Context Protocol (MCP)?

My philosophy is simple: **Native means infinite owned flexibility. Everything else is a distraction.**

But learning where to draw that line was painful.

### The Illusion of "More is Better"

In earlier versions of this architecture, I thought an agent's capability was directly proportional to the size of its toolkit.

I shipped over 40 built-in native Python tools. I had 10 different variants just for file editing: tools for structural editing, tools for LLM-based diffs, tools for appending, tools for targeted string replacement. I had separate tools for different types of codebase navigation, separate tools for specific platform executions, and tools for every minor state transition.

It was a design mistake.

If you give an LLM a toolbox with 40 highly specific, overlapping items, you do not make it smarter. You induce decision paralysis. The model ends up wasting precious reasoning cycles constantly debating whether to use `read_file`, `explore_code`, or `search_code`. Worse, when tools overlap, the model will often pick the slightly wrong one and hallucinate the parameters to force it to fit.

There is also a brutal economic reality: tool schemas cost tokens. Injecting 40 complex JSON schemas into the system prompt consumes thousands of tokens of overhead on every single turn. That is pure context pollution. It crowds out the actual conversational history and workspace context.

### The Great Consolidation

I spent weeks ruthlessly cutting and merging. Those 40+ tools were compressed into a sharp, unified core of around 20 native tools.

The consolidation was not random. It followed a principle I discovered through pain: **one powerful abstraction per domain beats ten specific tools every time.**

#### File Editing: From Ten Tools to One

In earlier versions, file editing alone had at least ten different tools. There were tools for structural editing, tools for LLM-powered diff generation, tools for targeted string replacement, tools for appending content, tools for inserting at specific lines, tools for creating files, tools for viewing files, and platform-specific variants that handled line endings differently. Each tool had its own JSON schema, its own parameter names, its own edge cases.

The model was constantly confused. Should it use `edit_file` or `str_replace`? What about `append_to_file`? What about `write_new_file`? The overlap was enormous, and the LLM would regularly pick the wrong one, then hallucinate the parameters for the tool it chose.

I crushed all of those into a single `str_replace_editor` that exposes four commands behind one tool definition: `view_file`, `create_file`, `insert_text`, and `undo_last_edit`, plus structured `edit_mode` options. One tool. One schema. One mental model. The model learns a single interaction pattern and uses the `command` parameter to express intent.

The details inside that tool matter. For code, `ast_code_editor` line/symbol tools and `edit_mode=range|patch` avoid brittle substring matching. Multi-file edits are sequential tool calls; checkpoints cover rollback when atomicity matters. `undo_last_edit` gives the model a bounded session-scoped undo instead of requiring checkpoint rollbacks for small mistakes.

That level of design — making the tool smart enough that the model does not need to learn a library of alternatives — is what reduces hallucination in practice. The tool does not assume the model will always provide perfect input. It normalizes whitespace when matching, provides clear error messages when a match fails, and validates paths against the project root to prevent writes outside the workspace.

#### Shell Execution: Platform-Agnostic by Default

Platform-specific commands were hidden behind a single `bash` tool that detects the OS internally so the LLM does not have to guess. The tool description dynamically changes based on the detected shell — if running on Windows with Git Bash, it says so explicitly and lists the available commands. If running in native PowerShell, it adjusts.

The key insight was that the model should never have to choose *which terminal tool* to use. That is an environment detail, not a reasoning decision. By absorbing the platform detection into the tool itself, the model's action space stays constant regardless of whether the user is on macOS, Ubuntu, or Windows 11.

The tool also manages persistent sessions. Environment variables, virtual environments, and the working directory survive across calls. That matters because real engineering work is stateful — you activate a venv, set environment variables, cd into a subdirectory, and then run commands. If each command were a fresh subprocess, the model would need to re-establish its entire environment on every turn.

One detail I am proud of: the tool supports a `truncation_strategy` parameter (`tail_heavy`, `head_heavy`, `balanced`) for long command outputs and a `grep_pattern` for filtering terminal output before it hits the context window. The model can say "run the tests but only show me the failures." That is not just convenience — it is a direct defense against context pollution from verbose command output.

#### Reasoning Tools: The Cognitive Triad

The massive multi-agent orchestration layer — the MetaSOP system with its role profiles, Standard Operating Procedures, and provenance chains — was replaced by three semantic reasoning tools: `think`, `finish`, and `task_tracker`.

`think` is deceptively simple. It logs a reasoning step without executing any action. The model uses it to brainstorm fixes, plan refactors, debug hypotheses, or weigh trade-offs before committing. It sounds trivial, but it is one of the most important tools in the entire system because it gives the model a structured place to reason without being forced to act. Without it, models will often act prematurely just because they feel pressure to produce a tool call. `think` relieves that pressure.

`finish` signals task completion. It requires a summary message, a list of completed steps, and suggested next steps. But calling `finish` is not enough — the task validation service independently walks the `task_tracker` and blocks the finish if any steps are still active. The model cannot cheat its way past this gate. It also accepts an optional `lessons_learned` field — observations about the task that get persisted for future runs. That is not self-improvement in the grand ACE sense. It is scar tissue. Tiny, practical lessons that accumulate quietly.

`task_tracker` maintains a structured plan. It has exactly two commands: `update` (create or overwrite the entire plan as a JSON list with `todo`, `doing`, and `done` statuses) and `view` (read the current plan). Full replacement semantics. The plan is persisted to `active_plan.json` in the workspace's agent state directory. The compactor reads this file to anchor in-progress tasks as essential events that survive context compaction. Without the tracker, the model would lose its own plan during long sessions when history gets compressed.

Together, those three tools replaced an entire multi-agent team with something cheaper, faster, and harder to game. The model thinks, tracks its own work, and finishes when the work is actually done. No role profiles. No YAML schemas. No provenance chains. Just discipline.

### Why These Tools Must Be Native

What remained were only the tools that form the *nervous system of the agent*.

I kept them native because they require zero RPC overhead. They need synchronous access to the workspace state, the circuit breakers, and the safety gates. When the agent updates the `task_tracker`, it is not just writing to a JSON file — it is synchronously triggering the validation service to update the ledger and check whether the agent should be allowed to finish. When the agent calls `bash`, the command analyzer immediately classifies the command against over forty threat patterns across critical, high, and medium severity tiers before the command ever reaches the shell. When the agent calls `str_replace_editor`, the tool validates the path against the project root, checks for writes to sensitive paths like `.ssh/` or `.env`, and for Python files, even runs an AST parse on the content to catch obviously broken output before it reaches disk.

Those safety gates cannot tolerate network latency. They cannot tolerate RPC failures. They cannot tolerate the ambiguity of an external server silently dropping a validation check because of a timeout. If a tool fundamentally alters or observes the agent's run-state, it must be native.

There is a clean dividing line here: **native tools touch the control loop. Everything else is external.** The `task_tracker` blocks the finish gate. The `bash` tool feeds the stuck detector and the circuit breaker. The `checkpoint` tool manages durable workspace state for rollback. The `think` tool shapes the reasoning trace that the compactor preserves. Every native tool participates in the state machine. That is why they are native.

### The MCP Gateway Masterpiece

But what do you do about the rest of the world? Browser automation, GitHub search, Jira integration, Slack messaging?

The ROI on reinventing a browser automation framework natively is zero. That is what the Model Context Protocol (MCP) ecosystem is for.

However, if I just plugged 50 external MCP tools into the agent, I would instantly recreate the context pollution problem I had just solved.

The solution was the **Single Gateway Tool**.

Instead of exposing every external MCP schema to the LLM, Grinta natively implements exactly one tool for the outside world: `call_mcp_tool(tool_name, arguments)`.

The system prompt dynamically injects the available external MCP tools as a plain text list — tool names and short descriptions, not full JSON schemas. The cost difference is enormous. A full JSON schema for a single GitHub tool might be 150 tokens. A plain text line saying "search_repositories: Search for GitHub repositories by query" is 12 tokens. When you have 40 external tools, that is the difference between 6,000 tokens of overhead and 500.

When the model determines it needs to search GitHub, it calls the native gateway tool with the tool name and arguments. The native gateway intercepts the call, validates the tool name against the registered MCP servers, and async-routes the request through a persistent client session to the correct external server.

The persistence of the MCP client session matters. Each MCP server connection is opened once at startup and kept alive for the lifetime of the conversation. The client supports automatic reconnection with exponential back-off — up to five reconnect attempts with increasing delays from a 0.5-second base. If the connection drops mid-session, the client re-enters the session and refreshes the tool list without the agent ever knowing. That resilience is invisible to the model. It just calls the gateway and gets results.

The MCP integration also supports both transport protocols — stdio for CLI-first usage and HTTP (SSE) for richer integrations — and connects to all configured servers in parallel during bootstrap so one slow server does not stall the agent's startup. There is even a synthetic wrapper layer that provides composite tools like fuzzy search over cached component lists, reducing unnecessary round trips to remote MCP servers.

On top of all that, there is a diagnostic tool: `mcp_capabilities_status`, which reports the MCP health state — how many servers are configured, how many are connected, what tools are available. The model can call this to understand its own external capabilities at runtime.

This separation of concerns is the holy grail. The LLM's context window stays pristine. The model only has to master one interaction pattern for the entire outside world. And the agent retains infinite extensibility without sacrificing the tight, native control loop of its core cognition.

---

## The Prompt Architecture: Python over Jinja

In earlier versions of the architecture, I used Jinja2 templates for system prompt rendering.

It was a disaster.

I had over 600 lines of template spaghetti filled with `{% if config.permissions.file_write_enabled %}` conditionals. There were ten different "optimized" versions of the prompt lying around in the codebase, each slightly different, each claiming to be the latest. The logic was buried in Jinja's template DSL — a language that is phenomenal for rendering HTML and catastrophic for building prompts that need to change dynamically based on runtime state.

You cannot unit test a Jinja template the way you test a Python function. You cannot set a breakpoint inside a `{% block %}`. You cannot trace the rendering path through a debugger when the prompt comes out garbled. Every conditional in the template is a branch you can only verify by rendering the whole thing and eyeballing the output.

I think of prompt engineering as writing instructions. It is actually software architecture.

I ripped out Jinja entirely. Grinta now uses pure Python string formatting (`f-strings`) with static Markdown partials loaded from disk and dynamic sections assembled through simple Python control flow.

### Why Python Won

The prompt builder is a set of pure Python functions. Each section of the system prompt — routing, autonomy, tool reference, MCP injection, security policy — lives in its own `_render_*` function. Static sections are loaded from `.md` files on disk. Dynamic sections use f-strings and loops.

This part of the architecture became important enough that it deserves its own chapter later in the book. If this section is the system-design view, [15. Prompts Are Programs](15-prompts-are-programs.md) is the deeper argument for why prompt engineering stopped being prompt-writing and became software architecture.

The rationale was deliberately anti-glamorous:

- Direct Python control flow for complex conditional rendering, instead of learning a second DSL
- No impedance mismatch between the language of the prompt and the language of the system
- Standard Python debugging — breakpoints, print statements, stack traces — works everywhere
- Type-safe section assembly with IDE support

The result is a prompt builder that takes a context dictionary and returns a string. It is the most boring and most maintainable piece of infrastructure in the entire project.

### The Five Partials

The system prompt is composed from five static Markdown partials:

1. **`routing`** — Tool routing strategy. This tells the model when to prefer `search_code` over `bash grep`, when to reach for the LSP query tool for precise symbol references, and when to batch commands instead of running them one at a time. It encodes the lessons I learned from watching early agents make terrible tool choices.

2. **`autonomy`** — The operating mode. Grinta supports three levels: `full` (execute all steps without asking), `balanced` (ask for risky actions), and `supervised` (confirm everything). Each level gets a different block injected into the prompt with explicit behavioral instructions and checkpoint hints.

3. **`tools`** — Tool usage discipline and fallback patterns. This is where the prompt enforces the philosophy: prefer structured tools over raw shell commands for file operations, do not use `cat` or `grep` for source code reading, do not create files with shell redirection when `str_replace_editor` exists.

4. **`tail`** — The closing behavioral instructions. Turn limits, budget reminders, and final rules that need to survive in the model's attention because they appear at the end of the system message.

5. **`critical`** — The hardest constraints. Things like "do not finish until the task tracker is terminal" and "do not write files with shell commands." These are separated so they can be weighted differently if needed.

### Why Markdown and XML?

I removed deeply nested JSON schemas and Jinja conditionals in favor of Markdown headers and XML tags.

Why? Because LLMs are trained heavily on GitHub, StackOverflow, and technical documentation. Markdown is their native tongue. They have seen millions of `## Headers` and `- bullet points` during pre-training. When I write the system prompt in Markdown, I am writing in the format the model has the deepest statistical familiarity with.

XML tags — `<TOOL>`, `<AUTONOMY>`, `<TASK>`, `<MCP_TOOLS>` — provide structural boundaries that the model naturally parses well without confusing them for user input. The model has seen enough HTML and XML in its training data that these tags act as reliable delimiters. They are not decoration. They are structural markers that help the model segment the system prompt into distinct cognitive zones.

This combination — Markdown for content, XML for structure — dropped the LLM friction to zero. A prompt that is easy for a Python parser to build is generally easy for an LLM to read.

### The MCP Injection Pattern

The prompt builder also handles MCP tool injection dynamically. The available MCP tools are passed in as a plain text list — tool names with descriptions. Server-level hints guide the model on when to use each MCP server. All of this is injected into a single `<MCP_TOOLS>` block instead of polluting the tool schema array.

This is the prompt-level expression of the Single Gateway Tool philosophy. The model sees the MCP tools as a menu, not as a set of function definitions. It picks a tool from the menu and calls the gateway. The prompt builder makes the menu readable while the gateway makes it executable. Two different engineering concerns, cleanly separated.

### The Tier System

One subtle but important detail: the prompt has two tiers.

The **base tier** is the normal operating mode. It includes the standard routing, autonomy, tool reference, and security sections.

The **debug tier** activates when the agent has encountered recent errors or is performing elevated-risk file operations. In debug mode, the prompt builder injects additional context — including lessons learned from the project's `.grinta/lessons_learned.md` file if it exists. These are the persistent scar-tissue notes from previous runs.

This two-tier system prevents prompt bloat during normal operation while providing the model with extra guidance exactly when it needs it most. The system does not dump every possible instruction on every turn. It escalates.

- mental model clarity
- long-term maintenance

That is also why I cared about cleanup and migration. The product contract is project-scoped local state, and the code has one-off migration logic specifically to pull legacy storage back into that shape instead of letting random fallback paths live forever. The local file store writes atomically through a temp file plus an atomic replace, can force-sync when the write really matters, and even retries deletes to survive Windows file-locking nonsense. That is not glamorous design work. It is the kind that stops local-first tools from feeling fake.

A serious local-first system should act like it respects its own filesystem contract.

---

## SQLite vs Bigger Database Thinking

This is another place where the SaaS-to-CLI pivot reshaped the architecture.

When you are thinking like a hosted multi-user platform, database thinking naturally trends toward heavier infrastructure. Once the product becomes local-first, the question changes.

You stop asking:

"What would look enterprise-grade in a cloud architecture?"

and start asking:

"What gives the user durable, reliable behavior with the least unjustified infrastructure burden?"

That is why optional SQLite acceleration and file-backed persistence make sense in Grinta's current architecture, while heavier database dependencies were pushed out of the default path.

The SQLite side is intentionally modest and intentionally serious. It is one database per conversation, with WAL mode enabled, a query-only read connection, and indexes on event type and source. That gives the system faster reads and stronger replay behavior without asking the user to operate external infrastructure just to run a coding agent on their own machine.

This is not anti-database ideology.
It is product-aligned system design.

Use the heavier pieces where they actually solve the current shape of the problem.
Do not drag them everywhere because they make the architecture sound impressive.

---

## Tree-sitter: Because Structure Matters

One of the easiest ways to make a coding agent look useful is to let it do broad string replacement.

One of the easiest ways to make it dangerous is to stop there.

Tree-sitter mattered to me because source code is not plain text in any meaningful engineering sense. It is structured syntax.

### Why It Was Worth the Dependency

Tree-sitter enables the system to reason about code with more structure awareness, which matters for:

- safer edits
- symbol-oriented changes
- more reliable refactoring behavior
- better syntactic awareness across languages

That value shows up in more than one place. It powers structure-aware editing, and it also shows up in the graph-based retrieval system, where code files can be indexed into files, classes, functions, imports, and call relationships instead of being treated like shapeless text blobs. Once you have a real parser, you should use it to give the model a better map of the codebase.

Earlier versions of the codebase had a more ambitious version of this. A graph memory store built a typed knowledge graph with nodes for files, classes, functions, variables, and concepts, connected by edges for imports, calls, definitions, inheritance, and references. A graph retrieval module combined that graph with a high-accuracy vector store that used hybrid vector plus BM25 search and cross-encoder re-ranking. It also had a hierarchical context manager with three tiers of memory — short-term, working, and long-term — plus explicit decision tracking and context anchors for information that should never be dropped.

Most of that was stripped during the SaaS-to-CLI pivot because the dependency surface was too heavy. What survived is simpler but still structural: Tree-sitter parsing, hybrid search, and re-ranking in a lighter package. I miss the graph memory sometimes. But carrying a NetworkX dependency and a full knowledge graph just to index code felt like building a library to read a pamphlet. The simpler version does enough of what matters.

This is not magic. It does not make every edit perfect. But it gives the system a stronger relationship to code shape than regex- or line-only editing.

That is worth real value in an autonomous tool.

### Why This Matters Beyond Editing

This is another example of a broader Grinta principle:

**the environment should help the model behave better.**

If you can give the model tools that operate on structured representations instead of raw ambiguity, you increase the odds of useful behavior.

That is system design serving agent design.

---

## The Config Cascade: A Real Tool Needs Real Configuration

One of the less glamorous but more important parts of a mature tool is configuration architecture.

Grinta's config system is layered instead of ad hoc.

It works as a cascade across:

- file-based configuration
- environment overrides
- CLI-level overrides
- section-specific processors and validation

More specifically, the system can ingest TOML configuration for core behavior, agent settings, model selection, security policy, runtime options, and compaction strategy. It can merge in JSON settings for compatibility, apply environment variable overrides with automatic type casting, and then layer non-persistent CLI overrides on top. Later sources win. That sounds boring until you try to support local interactive use, automated scripts, multiple providers, and per-project behavior without turning configuration into a fight.

In earlier versions, the config was heavier — branching into separate typed configs for LLM, agent, sandbox, security, condensers, runtime pools, Kubernetes, and more, plus separate TOML files for beta and production environments. That made sense for a multi-tenant hosted product. Grinta's config is simpler because it no longer needs to manage container orchestration, pool sizing, or per-user quota tiers. But the layered cascade pattern survived because that architecture was genuinely good regardless of product shape.

That matters because a serious tool eventually needs to support multiple modes of use:

- local developer workflows
- different model/provider setups
- automation scripts
- environment-driven deployment differences
- user-level customization without hacking source code

A messy config story eventually becomes a product tax.
A clean config story becomes leverage.

This is one of those areas where good engineering does not get flashy headlines, but users feel the difference immediately.

---

## Pydantic Everywhere: Because Loose Data Becomes Loose Thinking

Validation matters a lot in a system like this.

Agent tooling deals with:

- actions
- observations
- metadata
- configuration
- tool payloads
- persistence records
- provider-specific settings
- user-facing inputs

That is a lot of structured data moving across boundaries.

Using strong schema validation and typed models was not just about code cleanliness. It was about protecting the system from silent drift.

If the data contracts in an agent system are sloppy, the failures become much harder to reason about because the model is already a probabilistic component. The surrounding software should not be probabilistic too.

This shows up everywhere from `AppConfig`, `LLMConfig`, and `SecurityConfig` to `ValidationResult` and the structured `StateSummary` used by the summary compactor. Even the compaction layer is typed because I did not want one of the most fragile parts of the system to be held together by vibes.

The cost tracking system is a good example of why this matters in practice. Every LLM config carries explicit `input_cost_per_token` and `output_cost_per_token` fields so budget tracking works across providers. If those fields were loosely typed or optional-by-default, the budget limiter would silently fail to track costs for one provider while accurately tracking another. The user would burn through their budget without warning. Typed models prevent that failure from being invisible.

Pydantic helped make those boundaries explicit.

---

## The Executor: Write-Ahead Checkpoints and Crash Recovery

One of the less visible but most critical pieces of engineering is the executor — the component that actually invokes the LLM and processes the response.

The executor does not just call an API and return text. Before every LLM invocation, it writes a checkpoint to the Write-Ahead Log (WAL). The checkpoint records exactly what was about to be sent to the model — the parameters, the timestamp, the attempt count, the anchor event ID. If the process crashes mid-call, if the power dies, if the LLM provider drops the connection, that checkpoint survives.

On restart, the system detects the uncommitted checkpoint. If it is recent — less than five minutes old — the system blocks and requires manual review, because the agent's state is ambiguous. Was the LLM call completed? Did the model produce a tool call that partially executed? You cannot safely auto-retry in that window. But if the checkpoint is stale — older than five minutes — the system discards it automatically, because any in-flight LLM call has certainly timed out or failed, and there is no ambiguity to resolve.

This is not glamorous engineering. It is the kind of engineering that makes the difference between "the agent crashed and I lost thirty minutes of work" and "the agent crashed and picked up exactly where it left off."

### Deterministic Non-Streaming

One design decision that feels counterintuitive: the executor does not use native streaming by default.

Native streaming varies wildly across LLM SDKs. Some providers stream tool call arguments as incomplete JSON fragments. Some emit thinking tokens in separate events. Some interleave content and tool calls unpredictably. That variance is a source of continuous flakiness that poisons the reliability of the system.

Instead, the executor fetches the complete response in one call, then emits synthetic `StreamingChunkAction` events to give the UI the progressive appearance of streaming. The user still sees tokens appearing in real time. But internally, the system processes a complete, validated response — not a half-parsed stream that might break on a malformed JSON fragment from a provider that updated their SDK last Tuesday.

The async path supports true native streaming for environments that benefit from it, with dedicated handling for thinking tokens, redacted reasoning blocks, and accumulated tool call arguments. But the default path is intentionally boring and intentionally reliable.

---

## The Tool Assembly Pipeline

A detail that reveals a lot about how the system thinks at runtime is the tool assembly process — how the planner decides which tools to expose to the LLM on each turn.

This is not a static list. It is a layered assembly:

1. **Core tools** always present: `bash`, `think`, `finish`, the task tracker, the memory tools.
2. **Edit and search tools**: `str_replace_editor`, `search_code`, code structure exploration.
3. **Terminal and special tools**: the terminal manager, checkpoint/rollback, delegation.
4. **Optional feature tools**: LSP query (if the language server is available), signal progress (for external integrations), the blackboard (for state sharing).
5. **Meta-cognition tools**: a communication tool for expressing uncertainty or asking the user for clarification. This is crucial because the model should always have a way to say "I am not sure" without being forced to guess.
6. **The MCP gateway**: the single `call_mcp_tool` proxy that replaces fifty individual schemas.

The planner also checks for tool-model compatibility. Some models support tool choice forcing (where the system can require the model to use a specific tool), and some do not. The planner detects this via capability flags and adjusts accordingly.

This assembly happens on every turn. It is not expensive — the result is cached and invalidated only when the model or toolset changes — but it means the agent's capabilities can evolve during a session. If an MCP server connects mid-conversation, the new tools appear in the next turn's assembly. If a feature flag changes, the toolset adapts.

---

## The Audit Trail: Append-Only Accountability

One piece of infrastructure that most coding agents simply do not have is a real audit log.

Grinta writes an append-only JSONL audit trail for every session. Every autonomous action the agent takes — every file edit, every command execution, every finish attempt — gets an entry. Each entry records the action type, truncated content (capped at 1,000 characters for safety), the risk level assessment from the security analyzer, the validation result (blocked, requires review, or allowed), the execution outcome, any matched risk patterns that triggered the classification, and optionally a filesystem snapshot ID for rollback.

This is not just an operational nicety. It is an integrity mechanism.

If you ever need to understand what an autonomous agent did to your codebase — why it edited that file, why it ran that command, whether the security analyzer flagged it and the agent ran it anyway — the audit log has the answer. It is deliberately append-only so entries cannot be modified after the fact. It is deliberately structured so it can be queried by risk level or by action type.

The audit trail also enables compliance. If you are using Grinta in a professional environment where autonomous code changes need to be reviewable, the audit log provides that trail without requiring you to reconstruct it manually from git history and terminal output.

This is another example of infrastructure that came from the SaaS phase and proved valuable enough to survive the pivot. Multi-tenant environments need audit trails. But so does any system where an AI is making unsupervised changes to production-adjacent code.

---

## Security Hardening: Honest Safety Instead of Fake Sandboxing

This is a part of the project I care about a lot because AI tools are often marketed with security language that sounds stronger than the actual guarantees.

Grinta tries to be more honest.

The `hardened_local` execution profile is a stricter local policy layer. It is not sandboxing. It is not host isolation. It does not magically turn the machine into a prison for arbitrary code.

That distinction matters.

### What Hardened Local Actually Does

The hardened local profile adds stronger policy gates around things like:

- workspace-scoped command execution
- sensitive path access
- network-capable commands
- package installation commands
- background processes
- interactive terminal behavior
- allowlists for git, package, and network operations

The implementation is specific enough that I want to preserve the key details.

The command analyzer classifies every shell command before it reaches the runtime. It runs through over forty explicit threat patterns organized into four severity tiers: critical, high, medium, and low. Critical patterns catch the catastrophic commands — `rm -rf /`, `mkfs`, `dd` writes to `/dev/`, fork bombs, piped curl-to-shell, base64-decoded execution chains. High patterns catch privilege escalation (`sudo`), credential file access, `chmod 777`, `setuid/setgid` changes, recursive ownership modifications, `netcat` listeners, firewall modifications, and crontab changes. Medium patterns catch things like writing to `/etc/`, disk formatting, and service disruption. Anything that does not match a known pattern defaults to low risk.

The analyzer does not stop at Unix. It handles Windows-specific threats too: `Remove-Item -Recurse -Force`, `format C:`, `del /s /q`, and PowerShell-specific escalation patterns.

Crucially, the analyzer escalates chained shell commands and encoded payloads automatically. If a command uses pipes, semicolons, or base64 encoding to compose its actual intent, the analyzer treats the chain as a whole, not just the first command in the sequence. This matters because the classic evasion technique for automated security analysis is to hide a dangerous command inside a compound expression that looks innocuous in its first segment.

A separate security layer sits above the command analyzer. This layer watches for writes to sensitive paths — `/etc/`, `/usr/`, `/bin/`, `/sbin/`, `.ssh/`, `.env`, `.aws/`, `.gitconfig` — and for Python file writes, it parses the content at the AST level to catch obviously broken output before it reaches disk. If the model generates syntactically invalid Python, the system catches it before the file is written, not after.

The hardened local profile also defaults git operations to a read-only set — `status`, `diff`, `log`, `branch` — while leaving package installation and network access disabled until the user explicitly allows them. This is the principle of least privilege applied to an autonomous agent: the agent starts with fewer capabilities than it might need, and the user grants more as trust builds.

I spent more time on this than most people would expect, and I am not sorry about it. If you are building a tool that executes code autonomously on someone's machine, security is not a feature. It is a prerequisite for trust.

This is a real improvement in local safety.
It is also still local host execution.

### Why I Designed It This Way

Because false security claims are worse than honest limits.

If the system can be safer by policy, great.
Do that.
But do not pretend policy hardening is the same thing as full sandbox isolation.

That is another example of Grinta's broader design ethic: **be useful, be safer, and be truthful about what the system is.**

---

## Terminal Handling: Optional Power Beats Mandatory Burden

Terminal design is one of the places where system design and product philosophy collide.

Grinta's tool layer exposes terminal sessions as explicit session-oriented operations:

- open
- input
- read

Those are not just user-facing words. They map directly onto typed actions in the ledger, which means terminal sessions get the same persistence and replay semantics as other work. That is a good example of system design serving product design: terminals are treated as real first-class state, not as a side channel.

That is important because interactive engineering work cannot always be modeled as single fire-and-forget shell commands.

At the runtime level, the environment can take advantage of tools like tmux when they exist, but it does not make them mandatory. If tmux is not present, the runtime falls back instead of turning the whole product into a non-starter.

This matters for three reasons.

### 1. Cross-platform respect

A local coding agent should not silently become "Linux first, everyone else second" unless it is prepared to admit that explicitly.

### 2. Better defaults

Advanced users can still go deeper. New users are not punished for not having the perfect terminal stack.

### 3. Honest capability layering

Optional advanced power is a much better product pattern than mandatory hidden infrastructure.

---

## The Plugin System: Controlled Extensibility

A system like Grinta eventually needs extensibility.

But extensibility is another place where projects can hurt themselves. A plugin system that is too loose creates chaos. One that is too rigid becomes ornamental.

Grinta's hook and plugin story matters because it gives the system room to grow without turning the core into a junk drawer.

And this is not a vague promise for later. The LLM layer already exposes `llm_pre` and `llm_post` plugin hooks. The runtime can initialize plugin commands. The recall system can surface MCP tools from repo playbooks. And the operation pipeline composes 12 middlewares before execution. Extensibility in Grinta is controlled on purpose.

This is another reason I think of Grinta as more than an agent loop. It is a platform surface, but one that is trying to stay disciplined.

---

## The CLI Was Part of the Architecture Too

I do not think the CLI is just a shell around the real system.

It is part of the product architecture.

That is why I spent time on `prompt_toolkit` integration, slash commands, tab completion, history, a live HUD, a reasoning display, and a startup experience that actually feels intentional. The CLI is where the user forms trust in the engine. If the system is powerful but the control surface is clumsy, people will still experience it as weak.

I know some of those details sound small compared to the heavier architecture in this chapter. I do not think they are small. A HUD, a clean command surface, or even a dramatic ASCII splash screen can be the difference between a system that feels alive and one that feels like an internal tool somebody forgot to finish.

---

## Dependency Optionalization: Matching the Product Shape

One of the most mature engineering moves in this project was trimming base dependencies and moving some of the heavier ones into optional groups.

That includes infrastructure-shaped dependencies that made more sense in earlier, heavier architectural phases than they do in the default local-first CLI path.

The concrete examples matter. Internal Redis-backed runtime support was removed, with Redis kept only as an optional extra because one database skill still exposes a `connect_redis()` helper. `asyncpg` moved out of the base install and into the `database` extra. That is what architecture discipline looks like at the dependency level: the install surface should match the product you are actually shipping.

This matters because dependencies are architecture.

They are not just install lines. They are assumptions about:

- how the tool runs
- what the user must carry
- what environments are easy or hard to support
- how much accidental complexity becomes the user's problem

Making more of that optional was part of making Grinta truer to itself.

---

## Why This Chapter Matters

This chapter matters because it shows that the intelligence of a coding agent is only part of the story.

What makes Grinta serious is not just that it can reason about code. It is that the surrounding system was designed with discipline:

- explicit transport choices
- layered configuration
- structured editing
- strong validation
- local-first persistence
- honest security boundaries
- platform-aware terminal behavior
- dependency discipline
- model independence

That is software engineering.
Not just agent engineering.

---

## What Comes Next

The final chapter is about what remains unfinished, experimental, or in motion.

Because this project is not a polished fairytale. It is a real system with known limits, unfinished edges, and a future that still has to be built.

That is where I end.

---

← [The Giants' Playbook](05-the-giants-playbook.md) | [The Book of Grinta](BOOK_OF_GRINTA.md) | [The First Fixed Issue](08-the-first-fixed-issue.md) →
