# 27. Token Economics and the FinOps Trap

In the SaaS phase of Grinta, I envisioned a multi-agent system spinning up infinite sub-agents to parallelize work. In my head, I'd have an Architect, a QA, a DevOps, and a Coder working simultaneously.

Then I ran it on a medium-sized refactoring ticket. Thirty minutes later, that single task had burned through $40 of Claude 3.5 Sonnet tokens.

The FinOps trap of agentic frameworks is that loops compound exponentially. If an agent hallucinates a tool call, and the tool returns a 10,000-line error trace, and the agent reads that trace to decide what to do next, you're suddenly paying for 10,000 tokens per turn just to watch the agent be confused.

## The Iteration Cap

The first defense I implemented was a hard iteration cap in the orchestration loop (`backend/orchestration/session_manager.py` equivalent). Other frameworks let agents run forever, assuming they'll eventually find the answer. I learned that an agent that hasn't solved the problem in 30 steps is almost never going to solve it in 31 steps. It is stuck in a local minimum. Killing it is cheaper than hoping it figures it out.

## Context Compaction as Cost Control

Context compaction isn't just about fitting within the LLM's context window; it's about budget. In `backend/context/compactors.py`, I built multiple strategies because preserving token efficiency translates directly to saving money. Summarizing old turns and aggressively truncating command outputs prevents the token count from ballooning artificially.

## High/Low Routing

Another realization was that you don't need a frontier model ($15/1M tokens) to check if a bash command exited with `0`. For simple confirmation and extraction tasks, small local weights or secondary APIs can be used, reserving the expensive reasoning cycles for the actual orchestration engine (`backend/engine/`).

The reality is that a single agent, operating with strict constraints, focused memory, and precise tools, is mathematically more cost-effective and practically more reliable than an unconstrained swarm of models chatting with each other. A solo developer can't afford to run unstructured swarms.

The FinOps trap forces you to become a better architect.

---

← [The Observability Black Hole](26-the-observability-black-hole.md) | [The Book of Grinta](README.md) | [The Latency Veil and Human Trust](28-the-latency-veil-and-human-trust.md) →
