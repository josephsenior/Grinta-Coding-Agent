# 45. The Product Surface Became Real

There is a quiet phase in a serious project where the hardest work is no longer
inventing the engine.

It is making the engine survivable for other people.

For a long time, Grinta had the deeper machinery: the event stream, the
orchestrator, the inference layer, the file API, the safety gates, the compactor,
the retry logic, the terminal manager. Those pieces were real. They were also
easier to respect from inside the codebase than from the user's chair. A person
using the tool does not experience "23 orchestration service files." They
experience whether startup works, whether the UI explains itself, whether the
agent appears stuck, whether settings are discoverable, and whether a session can
be resumed without ceremony.

This chapter is about the period where that lesson stopped being theoretical.

---

## The TTY Became Its Own Product Surface

The earlier return of the interface started as a HUD. That was the right first
move: show tokens, cost, model, state, and useful runtime status without burying
the user in raw logs.

But a HUD is not enough once sessions become long and interactive.

The current repo routes interactive TTY startup through the Textual app:

```text
launch.entry
  -> backend.cli.entry
    -> backend.cli.main
      -> backend.cli.tui.main
```

That matters because the interactive surface now has real product responsibility:

- transcript cards instead of raw observations
- settings and sessions dialogs
- keyboard bindings for interruption, transcript copy, sidebar toggling, and help
- a persistent HUD with model, tokens, cost, MCP/skill counts, and runtime state
- load-earlier and replay mechanics for long sessions
- card-level rendering for terminal commands, file reads, edits, browser activity, MCP, workers, search, and LSP
- backpressure-aware event draining so the UI does not collapse under noisy runs

This is not the old Textual TUI coming back with nicer colors. It is a different
kind of UI. The old one was trying to make the project feel finished. The current
one exists because long-running agents need a cockpit.

That word is not marketing. In an agent loop, the interface is part of the safety
system. If the user cannot see whether the agent is thinking, waiting, retrying,
or asking for approval, they cannot make good intervention decisions. A bad
interface turns the user into a panicked supervisor. A good interface lets the
user stay calm long enough for the system to recover.

---

## Piped Input Stopped Pretending To Be Interactive

The Textual app is the right surface for a human sitting in a terminal.

It is the wrong surface for piped input.

That distinction sounds obvious, but it took discipline to encode it as a first
class path. `backend.cli.main` now branches on stdin:

```text
TTY stdin      -> Textual TUI
non-TTY stdin  -> repl_noninteractive
```

The non-interactive runner matters because automation should not inherit a
full-screen UI just because the interactive product is better. Shell scripts,
CI tasks, smoke checks, and one-shot prompts need plain input and plain output.
They need the same engine, not the same screen.

This split is one of those small architectural choices that pays rent
everywhere. It keeps the TUI honest as a human interface and keeps automation
honest as automation.

---

## Launch Became Part of Trust

One of the least glamorous fixes in this phase lives in `launch/entry.py`.

The installed `grinta` console script cannot assume that importing
`backend.cli.entry` will import *Grinta's* `backend` package. Users run tools
inside arbitrary repositories. Some of those repositories have their own
top-level `backend/` package. If Python import precedence grabs the user's
package instead of Grinta's package, startup fails in a way that looks haunted
from the outside: "I installed the tool, but it imports my app."

The launcher now resolves the installed or editable distribution path first,
prepends the correct project root to `sys.path`, and runs the entry file by path.
That is not flashy agent engineering. It is packaging hygiene. But packaging
hygiene is product trust.

A local-first tool lives inside other people's repositories. That means it has
to be careful about namespace collisions, cwd assumptions, project roots,
settings roots, and `.env` loading. A cloud product can control the runtime. A
local tool is a guest in a messy house.

This phase taught me that startup is not separate from architecture. Startup is
where the architecture either keeps its promises or immediately makes the user
debug your assumptions.

---

## The Model Matrix Got Wider

The old model-agnostic story was already real: OpenAI-compatible, Anthropic, and
Google-native client paths, plus local runtimes.

The current project state is broader. The catalog directory now carries provider
files for Anthropic, Cerebras, DeepInfra, DeepSeek, DigitalOcean, Fireworks,
Google, Groq, Lightning, Mistral, NVIDIA, OpenAI, OpenCode routes, OpenRouter,
Perplexity, Together, Vercel, and xAI. Local discovery lives under
`backend.inference.discover_models`, not in an older `backend.llm` namespace.

That does not mean every provider is equally strong for autonomous coding. It
means the system has moved from "we can point at a few APIs" to "provider
support is data-shaped where possible, client-shaped where necessary."

That distinction matters. A model launch should often be a catalog update, not a
new branch in the inference code. The hard cases still exist: reasoning wires,
temperature stripping, max-token naming, tool-call shapes, local models with
weak schemas. But the philosophy is clearer now. The engine should not have to
know the personality of every provider. The provider layer should absorb that
mess and present the agent with one stable contract.

---

## The File API Settled Into a Smaller Shape

This is one of the places where the project grew by shrinking.

The public file API is now centered on:

- `read`
- `find_symbols`
- `create`
- `edit_symbol`
- `replace_string`
- `multiedit`

The rule survived the churn: **read may search, write must target**.

That sentence looks simple because the complexity moved behind the facade. The
model does not choose between a dozen editing transports. It chooses intent. If
it needs context, it reads. If it needs structure, it finds symbols. If it needs
to create, it creates. If it needs to modify code, it edits a symbol. If the
file is prose, config, generated code, or otherwise unsuitable for AST edits, it
uses grounded string replacement. If the edit spans files, it uses `multiedit`
as a transaction.

The older docs sometimes named `write` or `read_symbol_definition`. Those were
true in earlier shapes of the system, but the current surface is smaller and
more honest. That is why this chapter belongs in the journey: the point is not
that the API name changed. The point is that the agent's mental load got lower.

---

## The Remaining Mess Is More Visible Now

This phase did not make the project perfect.

It made the remaining imperfections harder to hide.

There are still rough edges:

- contributor docs and startup scripts can drift from the canonical module paths
- UI code is now powerful enough to need its own discipline, not just enthusiasm
- release notes can preserve true historical facts while still confusing readers about current APIs
- counts in narrative docs age quickly when the codebase is actively decomposed
- optional features like browser, RAG, MCP, and debugger support need clear boundaries so users know what is default, what is opt-in, and what is experimental

That is uncomfortable, but it is healthy. A project with visible rough edges can
be repaired. A project that hides them behind a perfect README teaches users to
distrust every claim.

---

## What Changed In Me

The early version of me wanted the project to look impressive.

The current version wants it to be legible.

That is a different ambition. It changes what you value. You start caring about
boring entrypoints, fallback paths, install metadata, support matrices, release
checklists, and whether a sentence in a doc accidentally implies a guarantee the
runtime does not make.

It also changes how you judge the UI. The Textual interface did not return
because I missed having a pretty terminal. It returned because the agent had
outgrown raw scrollback. A serious local agent needs a surface where users can
understand state without reading a forensic transcript every time something
interesting happens.

That is the product lesson of this chapter:

An engine becomes a tool when the user can tell what it is doing.

And Grinta, finally, is starting to cross that line.

---

← [The Empty Folder Trials](44-the-empty-folder-trials.md) | [The Book of Grinta](README.md) | [The Road Ahead](07-the-road-ahead.md) →
