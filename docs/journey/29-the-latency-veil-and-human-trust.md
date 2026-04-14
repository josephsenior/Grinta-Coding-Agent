# 28. The Latency Veil and Human Trust

When an agent interacts with a human, the human expects an immediate response. But when a task requires an agent to call the inference client (`backend/inference/`), read a file using `backend/engine/tools/io_read.py`, run `grep`, decide to run a `pytest`, and parse the output, that process can take 30, 40, or 60 seconds.

This is the Latency Veil. The human is staring at a blinking cursor.

In my Textual UI phase, I tried throwing spinning loaders everywhere. But spinning loaders don't build trust; they just confirm the agent hasn't crashed.

## Streaming Intent

To build user trust, I had to stream the agent's intermediate steps. And because I use an event-sourced architecture, the UI streams every tool execution in real-time. You don't see "Thinking..." you see:

- `[TOOL] read_file(tests/conftest.py)`
- `[TOOL] run_command(pytest tests/)`
- `[LLM] The test failed because of a missing fixture. I need to edit conftest.py.`

The UI (`backend/cli/reasoning_display.py`, `layout_tokens.py`) makes the invisible machine's thought process visceral and immediately apparent to the human.

## The Confirmation Middleware

Trust is also about blast radius. I've watched an agent confidently type `rm -rf` in what it thought was a scratch directory. It wasn't.

This is why `backend/cli/confirmation.py` became a core part of the system. High-risk commands run through a middleware validation check before execution. Tools like `apply_patch` or dangerous `run_command` segments pause the execution loop entirely, presenting a prompt to the user: "The agent wants to delete this file. Allow? [Y/N]".

This bridges the latency veil perfectly. The human knows what the machine intends to do before disaster happens.

Other agents prioritize 100% autonomy and ask for forgiveness. I learned that for developers building locally, asking for permission—and making it visually distinct—is the only way to build an agent that they actually want to turn their back on. You can't replace the human judgment layer; you just move it from writing the code to approving the patch.

---

← [Token Economics and the FinOps Trap](28-token-economics-and-the-finops-trap.md) | [The Book of Grinta](README.md) | [The Weight Divide: Local vs Hosted](30-the-weight-divide-local-vs-hosted.md) →
