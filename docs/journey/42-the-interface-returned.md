# 42. The Interface Returned

During Month 6 — the pivot — I removed the Textual TUI.

The decision was correct at the time. The TUI had been product theater: a pretty terminal interface that showed spinning spinners and animated panels but did not make the agent more reliable. It consumed development time, added a heavy dependency, and created the impression of polish around a system that was still finding its footing. Removing it was part of stripping Grinta down to its engine.

But observability is not polish. And that distinction took me a few more months to learn.

---

## Why It Came Back

The agent did not need a pretty interface. It needed an operational interface.

When the agent ran for ten minutes on a complex task, the user had no idea what was happening. Was it thinking? Stuck in a loop? Waiting for a tool to finish? Burning through tokens on a hallucinated tangent? The terminal scrolled past, and the only way to answer those questions was to read every line of output.

That is not a UX problem. It is a reliability problem. If the user cannot tell whether the agent is making progress, they cannot decide whether to intervene. And if they cannot decide whether to intervene, they either watch the budget burn or abort prematurely.

The TUI came back as a HUD.

---

## What the HUD Shows

The current interface is not the Textual TUI I removed. It is a lean, dependency-light terminal layer that shows:

- **Cost** — running USD total for the session. No surprises at billing time.
- **Tokens** — prompt, completion, and total token counts.
- **Latency** — time since the last tool call completed, so you can see when the model is thinking.
- **Breaker state** — whether the circuit breaker is open, warning, or closed. If it is open, the agent is in recovery mode.

These four numbers replaced dozens of lines of scrolling log output. They give the user a dashboard-level view of agent health without requiring transcript reading.

The mode switch (`/mode`) and autonomy level (`/autonomy chat/plan/agent`) are also visible in the HUD bar, so the user can see at a glance what contract the agent is operating under.

---

## Cards, Not Logs

The tool output layer also changed. Instead of dumping raw tool observations into the terminal as unformatted text, the interface renders them as titled cards:

- **File creation, editing, and read** cards show the file path and a preview.
- **Shell command** cards distinguish batch execution from interactive terminal sessions.
- **Search results** cards show matches with line numbers.

Each card type is designed to make the output useful without overwhelming the daily user. The goal is not to hide information — the full output is always available — but to structure it so the user can scan rather than parse.

---

## Empty States and Transitions

One of the smaller but telling improvements: empty states.

When the session starts, the interface shows a clear empty state rather than a blank terminal. When the mode changes, the HUD updates immediately so there is no ambiguity about what contract the agent is operating under. When a task completes, the finish gate result is displayed prominently rather than buried in logs.

These are not cosmetic changes. They are answers to specific confusion points that emerged from watching people use the system. Every empty state, every transition animation, every card layout — each one exists because someone asked "what is happening right now?" and the interface did not answer.

---

## Pretty UI vs Operational UI

The difference between the old Textual TUI and the current HUD is the difference between making something look good and making something useful.

The Textual TUI made Grinta look like a polished product. The current HUD makes Grinta explain itself. One was about perception. The other is about trust.

The interface returned because I stopped treating it as a cosmetic layer and started treating it as a reliability layer. If the user cannot see what the agent is doing, they cannot trust what the agent has done. And an agent the user does not trust will be interrupted, overridden, and eventually abandoned.

---

← [The Mode Split](41-the-mode-split.md) | [The Book of Grinta](README.md) | [The Plugin Boundary](43-the-plugin-boundary.md) →
