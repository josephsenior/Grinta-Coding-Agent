# Chapter 24: Engineering the "Perfect" Prompt and the Criticism Bias Illusion

As Grinta evolved, the core prompt instructing the agent started to suffer from an inevitable disease: token bloat. Every time the agent failed or misbehaved, the natural instinct was to add another rule. The prompt grew longer, the context window filled up, and a phenomenon known as "lost in the middle" began to degrade performance. The agent was forgetting crucial rules simply because there were too many of them.

We needed a prompt that was dense but highly scannable. We needed to cover all areas—security, tool routing, execution discipline, file operations—without overwhelming the agent's attention mechanism.

## The Scannability Renaissance

We restructured the core prompt into clearly defined, XML-like sections. This allowed the agent to use them as mental anchors:

1. **The `<QUICK_REFERENCE>`**: A short, punchy block right at the top. It summarized the four most critical tenets: how to find things, how to edit files, safety communication, and execution discipline.
2. **The `<DECISION_FRAMEWORK>`**: A user-intent ladder. Instead of just telling the agent *what tools* to use, we instructed it on *how to react* to different types of user prompts. "How does this work?" meant reading and explaining. "Is there a bug?" meant diagnosing without fixing. "Fix this" meant full autonomous tool execution.
3. **Consolidation**: We merged redundant rules. The file operations and editor guides were combined to hammer home a single point: *Use editor tools for all file work. No shell commands for file content.*
4. **Dynamic Noise Reduction**: The MCP tool list was creating massive token bloat, listing all 57 tools explicitly. We capped it to list only the first 10 core tools explicitly, aggregating the rest into a brief "...and 47 more" summary.

## The Interaction Softening

One of the sneakiest bugs we encountered was the agent's reluctance to ask questions. It was trying too hard to guess the user's intent. Why?

Because the prompt originally said: *ask questions only when a true blocker remains.*

We softened this rule in the `<INTERACTION>` and `<CONFIDENCE_CALIBRATION>` sections. We explicitly told the agent: *If intent is unclear (e.g., "Is there a bug here?" vs "Fix the bug"), use `communicate_with_user` to offer options rather than guessing.* 

This simple shift transformed the agent from a reckless guesser into a collaborative partner.

## The LLM Criticism Bias

Out of curiosity, we asked the agent to rate its own prompt.

It gave it an 8.5/10. It praised the structure, the routing ladder, and the boundaries. But then, to justify not giving a perfect score, it started hallucinating critiques.

It complained that there was no "failure escalation" rule, even though the prompt explicitly stated: *After 3 failed approaches on the same sub-task... ask the user.*
It complained that the `<QUICK_REFERENCE>` was redundant with the tool sections—which is the fundamental definition of a quick reference!

This taught us a crucial lesson about LLMs and RLHF (Reinforcement Learning from Human Feedback) training: **LLMs have a severe "criticism bias" when asked to evaluate text.** They are trained to *always* find constructive feedback, even if they have to invent contradictions or ignore existing rules to do so.

We realized that chasing a 10/10 from the agent was a fool's errand. The true metric of a perfect prompt isn't the LLM's self-evaluation; it's the flawless, compliant execution of tasks without hallucination or failure. And by that metric, the new, dense, structured prompt was a resounding success.
