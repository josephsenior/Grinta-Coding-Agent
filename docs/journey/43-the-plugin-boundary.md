# 43. The Plugin Boundary

MCP — the Model Context Protocol — is one of the most promising ideas in the agent ecosystem. A standardized way for agents to discover and invoke external tools. No more hard-coding every API. No more per-provider tool adapters.

It is also one of the most dangerous ideas, if treated as infinite tool soup.

The promise of MCP is that any agent can use any tool. The reality is that dumping fifty MCP servers into an agent's context dilutes the model's attention, increases token costs, and shifts the agent's identity from "coding tool" to "vague tool orchestrator." A model that can do anything does nothing well.

Grinta has MCP support. But the philosophy behind it is deliberately constrained.

---

## The Selection

Grinta does not add random MCP servers. The current set is small and curated:

- **Web search** — real-time information retrieval when the agent needs current data.
- **Web fetch** — retrieve content from URLs for context gathering.
- **GitHub** — repository management, issue tracking, and PR operations.
- **Quality gates** — validation checks before the agent declares a task finished.
- **shadcn/ui** — component reference for front-end work.
- **Context7** — extended context retrieval for long-running tasks.

Each of these fills a specific gap that the native tool set does not cover. Web search and fetch replace what would otherwise require brittle screen-scraping or manual browser use. GitHub integration keeps the agent connected to the collaboration workflow. Quality gates add an external validation layer. shadcn/ui and context7 are domain-specific extensions for front-end and long-context work.

---

## Native vs Plugin

The boundary between native and plugin is intentional.

Native core tools — `read`, `write`, `edit_symbol`, `replace_string`, `multiedit`, `cmd_run`, `terminal_manager`, `grep`, `glob`, `analyze_project_structure` — are always available. They are taught in the system prompt as native truths. The model knows they exist, knows their interfaces, and relies on them for the central work of coding.

MCP tools are taught differently. They are declared in the tool schema rather than the prompt, discovered at runtime, and presented as capability extensions. The model can use them when relevant but does not depend on them for core behavior.

This distinction prevents MCP from becoming a crutch. If a capability is central to the agent's job — reading files, editing code, running commands — it must be a native tool, taught in the prompt, with a stable interface. If a capability is peripheral — fetching a web page, querying a GitHub issue — it can be an MCP tool, discovered at runtime, with a replaceable interface.

---

## The Technical Detail

MCP tools are integrated through a unified call layer that reduces token overhead. Instead of each tool registering its own schema independently, MCP tools are pooled into a single tool call structure with shared metadata. This keeps the tool list compact and the per-request token footprint predictable.

One area that still needs consolidation: duplicate fetch tools. Grinta has a native `web_fetch` heuristic tool and an MCP web fetch server. These should be unified so the model has one fetch entry point, not two. A model that has to choose between two ways to fetch a URL will occasionally choose the wrong one, and the cost is a malformed tool call that wastes a round trip.

---

## What MCP Should Not Replace

Some capabilities should never be MCP tools. They should be taught in the prompt as native truths.

The editing facade — `read`, `write`, `edit_symbol`, `replace_string`, `multiedit` — is the clearest example. If these were MCP tools, the model would not have them in its initial context. It would have to discover them, learn their interfaces at runtime, and rely on the MCP host to make them available. That introduces latency, uncertainty, and a dependency on the MCP transport layer for core operations.

The same applies to `cmd_run` and `terminal_manager`. If the model cannot run commands because the MCP server is down, it is not a coding agent anymore.

Quality gates are a different case. They could plausibly become automatic — triggered by the finish gate rather than requiring an explicit MCP call. That would move them from "optional plugin" to "compulsory validation layer," which is probably where they belong.

---

## The Principle

MCP is dangerous if treated as infinite tool soup. It is powerful if treated as a deliberate capability boundary.

The selection is not about what is possible. It is about what belongs. Web search belongs. Fifty random API connectors do not. GitHub belongs. A Wolfram Alpha calculator probably does not.

The plugin boundary is the decision about what the agent should always be able to do versus what it can sometimes do with help. Getting that boundary right matters more than the number of MCP servers in the config file.

---

← [The Interface Returned](42-the-interface-returned.md) | [The Book of Grinta](README.md) | [The Empty Folder Trials](44-the-empty-folder-trials.md) →
