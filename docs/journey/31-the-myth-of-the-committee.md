# 30. The Myth of the Committee

There is an obsession in the AI space with "Swarm Intelligence" or multi-agent systems. When you build an agent framework, the immediate temptation is to build a committee: an Architect agent, a Developer agent, a Reviewer agent, and a QA agent.

I built that. I spent part of my seven-month journey engineering a 20,000-line multi-agent planning suite complete with a conflict predictor, a message bus, and provenance chains.

And then I deleted it. Because the committee is a myth.

## The Babel Problem

When you have four agents talking to each other:

1. **Token Cost Explodes:** Every message is passed through four different context windows. A simple "I fixed the typo in `app.py`" costs 4x the tokens to process.
2. **Infinite Loops:** If the Reviewer agent says "This is wrong, fix the regex," and the Developer agent says "No, the regex is right," they will argue until you run out of API credits. They have no physical common sense, only token-prediction momentum.
3. **Loss of Coherence:** State handoffs between agents are incredibly fragile. Context compresses poorly across isolated actor boundaries.

I watched my Swarm burn through $40 on a single ticket just complaining to itself about a missing import.

## Orchestration Modes Over Autonomous Actors

I realized the answer wasn't multiple agents. The answer was a single, highly capable orchestrator (`backend/orchestration/`) executing different **Modes**.

Instead of switching _who_ is doing the work, Grinta switches _how_ the work is being done. The state machine (`backend/engine/`) transitions between stages: Planning, Execution, Tool Call, Validation, and Recovery.

The agent uses the same memory, the same identity, and the same context ledger. But when it enters the `validation` mode, the system constraints change. The rules of engagement change. The available tools change.

This is the key to Grinta's reliability. A single agent, guided by 21 orchestrated services and a strictly enforced pipeline. When the cycle complexities caused event-sourcing deadlocks, I didn't need to debug a conversation between four hallucinating AIs; I needed to debug a cyclic dependency in my Python code.

Other frameworks sell you a software engineering firm in a box. I realized I was building a tool, not a company. A single excellent developer with the right tools, strict validation, and an uncorrupted memory works faster and cheaper than a committee of four juniors.

Grinta is that single developer.

---

← [The Weight Divide: Local vs Hosted](30-the-weight-divide-local-vs-hosted.md) | [The Book of Grinta](README.md) | [The Road Ahead](07-the-road-ahead.md) →
