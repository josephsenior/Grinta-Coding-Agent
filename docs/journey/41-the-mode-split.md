# 41. The Mode Split

For most of Grinta's life, behavior was controlled by prompt instructions.

The system prompt told the model: speak here, do not speak there, finish only here, communicate only when blocked, use the task tracker carefully. Each instruction was a response to a real failure — the model finishing too early, the model chatting instead of executing, the model going silent when it should have asked for clarification.

Over time, the prompt grew denser and the contradictions grew sharper. "Do not ask for permission unless you are stuck" and "always ask before dangerous actions" could both be in the same prompt, and the model would oscillate between them depending on which paragraph it paid attention to in that inference step.

I was trying to solve a product architecture problem with prompt wording. That never works.

---

## The Realization

The turning point was watching a model drop into conversation mid-task — explaining what it was about to do instead of doing it — while another model on the same prompt charged ahead and broke something that a five-second clarification would have prevented.

The difference was not the prompt. The difference was the task shape, the model's mood, the phase of the moon. Two models. Same prompt. Opposite failure modes.

That is when I understood: **autonomy is not one mode.** It is a state machine with different conversational contracts, and no single prompt can encode all of them well.

---

## Three Contracts

The fix was product architecture, not prompt wording.

**Chat mode** — talk freely, no execution pressure. The model can ask questions, discuss trade-offs, explore ideas. No tools run unless the user explicitly asks for a task. This is the mode for thinking out loud.

**Plan mode** — think, clarify, produce an actionable plan. The model gathers requirements, asks follow-up questions, and writes a structured plan before any tool executes. The user reviews and approves the plan before execution begins. This mode prevents the most expensive failure pattern in autonomous agents: charging ahead on a misunderstood task.

**Agent mode** — execute tasks. The model plans, runs tools, validates results, and finishes. While work remains active, plain-text conversation is minimized. The model speaks only to report progress, ask clarifying questions when genuinely blocked, or declare completion. Small talk is suppressed until all work is done. This is the mode for getting things done.

---

## What the Mode Split Made Possible

Once the mode was an explicit state, the prompt could stop being a legal document.

Chat mode's prompt is short and open. Plan mode's prompt adds structure for requirement gathering and plan formatting. Agent mode's prompt adds execution discipline, tool calling rules, and finish conditions. Each prompt is tailored to its contract without worrying about the other contracts leaking in.

The mode also simplified the UI. The mode switch is visible in the HUD bar. The user can see at a glance whether the system is in thinking, planning, or executing state. The autonomy level (`/autonomy`) only matters in Agent mode, because Chat and Plan have their own interaction contracts independent of confirmation gates.

And crucially, the mode split made the system more honest. When the model is in Agent mode and the user types open-ended text, the model knows it should either execute or ask for clarification — not launch into a philosophical discussion. When the user wants to think out loud, they switch to Chat mode and the model knows it can relax.

---

## The Lesson

Mode split is not a feature. It is a recognition that different phases of work need different social contracts between human and agent.

The temptation is to encode all of them in one prompt and one tool set. That is what I did for months. It is what most agent systems do. And it creates models that are simultaneously too cautious and too reckless, because the prompt asks them to be both.

The mode split is the admission that prompt engineering has a ceiling, and beyond that ceiling you need product architecture.

---

← [The Facade Pattern and the Smaller File API](40-the-facade-pattern-and-the-smaller-file-api.md) | [The Book of Grinta](README.md) | [The Interface Returned](42-the-interface-returned.md) →
