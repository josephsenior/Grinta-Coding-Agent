# 12. Open Source Was the Better Business

There is a specific kind of freedom that comes from giving up on a business model.

I spent the first four months of this project building a SaaS. A multi-tenant, Kubernetes-orchestrated, Docker-containerized, React-frontend, PostgreSQL-backed, Stripe-billing, JWT-authenticated machine. I had the domain name. I had the pitch. I had the architecture diagrams.

And then I deleted it.

This chapter is about why making Grinta a local, open-source, CLI-first tool was not a failure of commercial ambition. It was the only way the tool could actually become what it was meant to be.

---

## The Economics of Autonomy

The fundamental problem with hosting autonomous coding agents is the economics of compute and context.

When you build a SaaS around an LLM, your margins are dictated by how efficiently you can turn API spend into customer value. A writing assistant can often do that in a handful of calls. An autonomous coding agent almost never can.

An agent does not solve a problem in one call. It solves it in thirty. It reads a file, searches the codebase, realizes it needs a different file, writes a test, watches the test fail, reads the error, patches the file, reruns the test, and only then finishes.

Every one of those thirty calls requires sending the entire conversation history, the active file context, the tool definitions, and the system prompt back to the LLM. The context window grows with every step.

If you run this as a SaaS, you are paying for all of those tokens. To make the unit economics work, you have to constrain the agent. You have to limit the context window. You have to force it to use cheaper, dumber models for the intermediate reasoning steps. You have to cap the total number of iterations. You have to build complex caching infrastructure because every cache miss eats your margin.

The business model puts you in direct opposition to the agent's capability. You want it to be smart; your AWS bill wants it to be fast and cheap.

## The Privacy Barrier

Even if you solve the economics, you hit the privacy barrier.

To fix a bug, an agent needs to see the code. To see the code deeply enough to understand the architecture, it needs to be able to grep the entire repository. To run the tests, it needs access to the environment variables, the internal dependencies, and the database schema.

If you are a solo developer working on a side project, giving a SaaS web app access to your GitHub repo is fine.

If you are an engineer at a mid-sized company, handing over your proprietary codebase, your internal API keys, and your test database credentials to a third-party startup's Docker container is an absolute career-ending non-starter.

The cloud model requires users to ship their context to the agent. The local model ships the agent to the context.

## The Local Honesty

When I finally ripped out the cloud infrastructure — the 20,000 lines of container orchestration, the webhooks, the Stripe integration, the Redis caches — the project didn't just get smaller. It got honest.

Grinta runs on your machine. It uses your API keys (or your local Ollama instance). It reads your files directly from your SSD. It runs your tests in your exact Python environment.

Because it runs locally, the cost of an iteration is borne by the user's API key, not a centralized SaaS budget. Suddenly, the agent doesn't need to be artificially constrained. It can afford to think deeper, search wider, and try more aggressive refactoring paths. If the user wants to spend $2 in API costs to fix a complex bug, they can. They aren't gated by a startup's arbitrary monthly token quota.

Because it runs locally, privacy is no longer something I have to simulate with elaborate isolation architecture. The code never leaves the user's machine except when it is sent to the LLM provider they explicitly configured. If they use a local model, the code never touches the internet at all.

### The Configuration That Trusts the User

Going local meant the configuration system had to be right. It could not be a dumbed-down settings page with three toggles. It had to give full control to the user while remaining opinionated about defaults.

The config system implements a three-layer cascade: TOML file, environment variables, CLI overrides. Each layer overrides the previous, so you can have a project-local `config.toml` checked into Git, override specific values with environment variables in CI, and override everything with command-line flags during development. That cascade is a standard pattern, but the discipline is in the grouping.

Configuration is organized into sections: LLM settings (model, API keys, temperature, max tokens, reasoning effort), agent behavior (autonomy level, iteration limits, confirmation mode, stuck detection threshold), security (allowed commands, blocked patterns, sensitive paths), context management (compaction strategy, max events, observation masking), and tool configuration (MCP servers, search behavior, file editing defaults). Each section has sane defaults so a minimal config — just an API key and a model name — produces a working agent. But every behavioral parameter is exposed for users who want to tune.

Budget caps deserve special mention. The config lets users set hard limits on total token spend per session and per task. When the cap is reached, the agent stops and reports what it accomplished. This is not throttling — it is user sovereignty over their own costs. A SaaS would cap tokens to protect *its* revenue. Grinta caps tokens to protect *the user's* wallet, and only when the user asks for it.

### The CLI as a First-Class Interface

The CLI is not a wrapper around an API. It is the primary interface.

Built on `prompt_toolkit`, the CLI provides a full interactive REPL with slash commands, tab completion, and persistent history stored at `~/.grinta/history.txt`. The slash commands expose system controls: `/help` for command reference, `/settings` to view and modify configuration at runtime, `/sessions` to list and `/resume` to continue previous sessions, `/autonomy` to change the autonomy level mid-session without restarting, `/model` to switch models without restarting, `/compact` to force a memory compaction, `/retry` to re-run the last failed action, `/status` to inspect the agent's current state, `/clear` to reset, and `/exit` to close.

The HUD — the display layer — operates in two modes: full and compact. Full mode shows the complete agent output including tool calls, observations, and reasoning. Compact mode shows a condensed view with just the essential actions and results. Users switch between modes based on whether they are debugging the agent's behavior or just using it as a tool.

Session persistence means you can close the CLI, reopen it tomorrow, and resume exactly where you left off. The event store replays the session, the memory manager reconstructs the context, and the agent picks up mid-task. That is not a convenience feature. That is a correctness requirement, because long coding tasks span hours or days, not minutes.

## The Pivot That Was Actually a Graduation

Deleting the SaaS was the hardest decision of the project. It felt like I was admitting defeat. It felt like I was downgrading from a "Startup" to a "Script."

But the moment I made it local, everything got better. The latency vanished. The execution layer became direct shell access instead of proxying through a WebSocket to a Kubernetes pod. The file synchronization stopped being a source of horrible race conditions.

More importantly, it became a tool I actually wanted to use myself.

A SaaS agent is a walled garden. A local open-source agent is a power tool. It lives in your terminal, next to your Git, your grep, and your compiler. It respects your environment. It doesn't ask you to upload your work; it joins you where your work already is.

### What "Your Machine" Actually Means

The phrase "runs on your machine" hides enormous engineering complexity, and the previous chapters document it. Cross-platform shell execution across three operating system families. Security analysis of every command before it touches the terminal. Write-Ahead Logging so a power failure does not corrupt your session. Persistent terminal sessions so the agent can manage long-running processes. Atomic file writes so a crash mid-save does not destroy your source files.

All of that infrastructure exists because "local" is not simpler than "cloud." It is differently complex. Cloud complexity is in orchestration, scaling, and multi-tenancy. Local complexity is in portability, safety, and resilience. The difference is who the complexity serves. Cloud complexity serves the operator. Local complexity serves the user.

That is the lesson that took me four months and 20,000 deleted lines to learn.

Open source was not the fallback plan. It was the only architecture that allowed Grinta to be uncompromising.

---

← [The Console Wars](11-the-console-wars.md) | [The Book of Grinta](README.md) | [The Hidden Playbooks](13-the-hidden-playbooks.md) →
