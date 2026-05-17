# 28. The Latency Veil and Human Trust

A human staring at a blinking cursor for 45 seconds does not feel like the agent is working. They feel like it has crashed.

This is the latency veil: the gap between what the agent is doing (calling the inference client, reading files, running tests, parsing output) and what the human perceives (nothing). The gap is real — a full tool round-trip can take 30 to 60 seconds depending on the provider, the context size, and the complexity of the tool output. But the human experience of that gap is what determines whether they trust the system or kill it.

In the Textual TUI phase, I tried the obvious solution: spinning loaders. They did not work. A spinner confirms the process has not crashed. It does not tell the human *what* the process is doing. It is the difference between watching a progress bar and watching a black box.

---

## Streaming Intent, Not Just Output

The event-sourced architecture made the solution possible: stream every tool execution as it happens, not after it completes.

```
[TOOL] read_file(tests/conftest.py)
[TOOL] run_command(pytest tests/)
[LLM] The test failed because of a missing fixture. I need to edit conftest.py.
[TOOL] str_replace_editor(tests/conftest.py) — lines 14–22
```

The HUD (`backend/cli/hud.py`) reinforces this by showing the agent state label in real time — `Running`, `Ready`, `Awaiting input` — so the human always knows where the agent is in its lifecycle. The reasoning display (`backend/cli/reasoning_display.py`) streams the agent's intermediate thoughts as they arrive, not as a batch after the turn completes.

The difference is subtle but critical. A spinner says "I am working." Streaming intent says "I am reading conftest.py because the test failed on a missing fixture." One is noise. The other is a narrative.

## The Confirmation Middleware

Trust is not just about visibility. It is about blast radius.

I have watched an agent confidently type `rm -rf` in what it thought was a scratch directory. It was not. The command analyzer (`backend/security/command_analyzer.py`) caught it — 40+ threat patterns across four severity tiers, with separate rule sets for Unix and Windows. But the real fix was the confirmation middleware: high-risk commands pause the execution loop and present the human with a choice.

```
The agent wants to execute: rm -rf /tmp/grinta-scratch/
Risk level: HIGH (recursive deletion)
Allow? [Y/N]
```

This bridges the latency veil in a different way. Instead of asking the human to wait through 45 seconds of silence, it gives them a moment of agency at the point where it matters. The human does not write the code. They approve the patch. That is a fundamentally different relationship.

Other agents prioritize 100% autonomy and ask for forgiveness. I learned that for developers building locally, asking for permission — and making it visually distinct — is the only way to build an agent they actually want to turn their back on.

## The Autonomy Knob

The confirmation system is not binary. It is controlled by the autonomy mode (`balanced`, `full`, `conservative`), which the user can toggle mid-session via `/autonomy`. The mode determines which risk tiers require confirmation and which pass through.

This is where the latency veil meets product design. In `full` mode, the agent runs without interruption — fast, but risky. In `conservative` mode, almost every write requires approval — safe, but slow. The `balanced` mode is the default because it matches how most developers actually work: trust the agent for reads and safe edits, but intercept anything destructive.

The autonomy knob is not a feature. It is a trust calibration instrument. And it exists because I learned that the right amount of latency is not zero — it is *exactly enough to catch the mistake before it happens*.

---

← [Token Economics and the FinOps Trap](28-token-economics-and-the-finops-trap.md) | [The Book of Grinta](README.md) | [The Weight Divide: Local vs Hosted](30-the-weight-divide-local-vs-hosted.md) →
