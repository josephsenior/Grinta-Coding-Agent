# 04. The Context War

If you have never built a long-running agent, context looks simple from the outside.

Just give the model more history.
Maybe summarize when things get too long.
Maybe keep the recent messages.
Maybe call it memory.

That is the beginner version of the problem.

The real problem is much harder.

A long-running agent is not just constrained by context window size. It is constrained by **attention quality**. A model can technically fit a lot of tokens and still behave like it understands much less than what you gave it. That gap between "fits in the window" and "stays cognitively useful" is where most context systems start failing.

This chapter is about how I learned that the hard way.

This was one of the most humbling subsystems in the entire project. It forced me to accept that "more context" and "better memory" are not the same thing, and that a model can be surrounded by information yet still behave like it forgot the plot.

---

## The First Attempt Was Too Simple

At first, I did what a lot of people would do.

I experimented with a small number of compaction strategies. Two or three approaches. Basic ideas. Enough to say, "yes, the system can condense history when needed."

That was not enough.

Because different tasks fail differently.

Some need recent conversation continuity.
Others need critical observations preserved.
Some need file-edit history.
Others need milestone summaries.
And some mostly need noise removed without collapsing causal structure.

A single compaction strategy cannot serve all of those needs well.
Neither can two.

That was the point where compaction stopped feeling like a utility feature and started feeling like one of the most intellectually demanding parts of the system. This was no longer about shaving tokens. It was about preserving the shape of thought across a long autonomous run.

---

## Why This Problem Is Deeper Than Truncation

A lot of systems still treat memory management like an input-length problem.

That is too shallow.

The actual questions are:

- What information is still causally important?
- What information is recent but irrelevant?
- What observations are verbose and safe to mask?
- What history must remain explicit because the agent may need to reason about it again?
- What can be summarized without losing the shape of the task?
- What details are important to recovery, validation, or planning even if they are old?

If you answer those questions badly, the model starts forgetting the task in more subtle ways than obvious truncation.

You get behaviors like:

- repeated inspection
- redoing work that already happened
- forgetting constraints
- losing confidence about what files changed
- drifting away from the original objective
- bloating the prompt with summaries that are technically accurate but cognitively weak

That is why I stopped thinking about compaction as compression and started thinking about it as **context engineering under attention limits**.

---

## Studying the Giants

At that point, I had to widen my frame.

I started thinking harder about how serious agents handle long sessions in production, even when they do not fully explain it publicly.

This was not about copying blindly. It was about reverse engineering the problem space.

What do mature agent systems appear to optimize for?

- recency
- salience
- explicit milestones
- preservation of critical failures
- removal of repetitive observations
- some form of compacted state representation
- balancing detailed history with behavioral coherence

That pushed me away from the naive idea that one "smart summary" would solve everything.

It would not.

The problem is too diverse.

---

## The Expansion to 12, Maybe 13, Moving Parts

So the system grew.

At one point, I had expanded the compaction system to around 12 strategies.

And sometimes, if I was being brutally honest about what was really happening, it felt like 13.

That was not because I wanted a flashy number.
It was because the problem genuinely required experimentation across multiple dimensions.

I needed different ways to handle:

- aggressive pruning
- recency preservation
- observation noise reduction
- structured summarization
- heuristic selection
- importance-based retention
- different task shapes and session trajectories

That phase of the project was important because it taught me a critical lesson:

**memory systems are not just about storing less. They are about storing the right shape of reality for the model to keep acting competently.**

The count got fuzzy because some of what I was building were pure strategies, some were meta-strategies, and some were composition layers. The live repo now ships 9 compactor implementations and a selector helper that makes the subsystem feel like 10 moving parts today. At the experimental peak, before trimming and consolidation, the working set felt more like 12 or 13. I do not want to erase that ambiguity, because it reflects how the subsystem actually evolved.

The earlier codebase still has the full 12-condenser set, and tracing the lineage tells the real story of what survived and what did not:

| Earlier Condenser | Grinta Compactor | What Happened |
| --- | --- | --- |
| `NoOpCondenser` | `NoOpCompactor` | Survived, renamed |
| `RecentEventsCondenser` | `RecentEventsCompactor` | Survived, renamed |
| `ConversationWindowCondenser` | `ConversationWindowCompactor` | Survived, renamed |
| `ObservationMaskingCondenser` | `ObservationMaskingCompactor` | Survived, renamed |
| `AmortizedForgettingCondenser` | `AmortizedPruningCompactor` | Survived, renamed (from "forgetting" to "pruning" — the word change is honest) |
| `StructuredSummaryCondenser` | `StructuredSummaryCompactor` | Survived, renamed |
| `SmartCondenser` | `SmartCompactor` | Survived, renamed |
| `CondenserPipeline` | `CompactorPipeline` | Survived, renamed |
| `BrowserOutputCondenser` | — | **Killed** — died with the BrowsingAgent. No browser means no screenshots or accessibility trees to mask. |
| `LLMSummarizingCondenser` | — | **Killed** — this was a rolling window with LLM-generated summaries. Its functionality was absorbed into `StructuredSummaryCompactor` which does the same thing with stricter schema constraints. |
| `LLMAttentionCondenser` | — | **Killed** — used structured output to make the LLM rank events by importance. Too expensive. Its core idea (importance-based selection) was folded into `SmartCompactor` where the LLM scoring is optional with heuristic fallback. |
| `SemanticCondenser` | — | **Killed** — scored events by semantic importance with cosine similarity. Promising idea but added embedding dependencies and was not reliably better than the heuristic scoring in SmartCompactor. |
| — | `AutoCompactor` | **New** — the selector layer did not exist in earlier versions. It was born from the lesson that strategy selection matters as much as strategy quality. |
| — | `auto_selector` | **New** — the threshold-based selector helper. |

That table is the honest archaeology. Three condensers were killed, two new components were added, and eight survived with renames and refinements. The "12 or 13" ambiguity was because `auto_selector` was sometimes treated as a 13th moving part even though it was really a wiring helper.

That messiness is valuable to me. I do not want this chapter to read like I calmly designed a perfect memory architecture from first principles. I pushed too far, kept too much for a while, learned where the complexity was earning its keep and where it was just showing off, and then cut it back.

---

## What Survived in the Current Architecture

The current Grinta architecture retains a more disciplined set of compactor strategies. The surviving system includes several important approaches, each solving a different memory problem.

All of them operate on a view abstraction built from event history, not on a naive chat transcript. That matters because the view layer has to account for prior compactions, pruned events, preserved summaries, and pending compaction requests. Even the substrate is more serious than it looks from the outside.

Every compactor implements the same protocol: receive a list of events, return a compacted list. The protocol is intentionally simple because the complexity lives in what each strategy considers important, not in how they interface with the engine. The compaction request itself flows through a metadata batching system — events are grouped into batches with a configurable maximum of 50, each carrying its own metadata. This prevents memory pressure during compaction of very long sessions where thousands of events need to be processed. Without batching, a 2000-event session produces a single enormous prompt that can itself exceed the context window, creating the absurd situation where your memory management system fails because it ran out of memory.

The auto-selector deserves its own moment. It does not just pick strategies randomly. It reads the session shape: event count, error density, observation volume, whether the model supports function calling (which determines whether structured summary compaction can use its tool-calling schema). The selector's decision tree is one of the most production-shaped pieces of logic in the entire system because it encodes empirically-derived heuristics about when each strategy actually helps versus when it makes things worse.

### No-op compaction

Sometimes the best compaction is none at all.

If the session is still within healthy bounds, forcing transformation can do more harm than good. This is a simple lesson, but an important one: compaction should not become a ritual.

In practice, the auto-selector reaches for no-op when the session is still small — less than about thirty events is often not a context problem yet. That sounds trivial, but it is one of the most mature choices in the whole subsystem: do not compact just because you built a compactor.

### Recent-events compaction

This keeps the most recent part of the session and drops older material aggressively.

It is simple, fast, and useful in situations where recency matters more than long historical nuance.

The implementation is intentionally blunt: keep the first few anchor events, keep the most recent tail, drop the middle. The selector biases toward it when the session is error-heavy, because in a failure spiral the newest loop usually matters more than the old success path.

### Conversation-window compaction

This is more careful than raw recency. It preserves recent windows while also keeping important adjacent structure, such as paired actions and observations, and file-edit-relevant context.

This matters because long sessions are not just a list of messages. They are causal chains.

This is one of the strategies I most want people to notice. The conversation window compactor always preserves system messages, user messages, file-write and file-edit actions, and the paired observations that explain what happened. It does not ask an LLM to summarize anything. It just refuses to destroy edit causality while still pruning the old noise around it.

The preservation logic is specific: it anchors task-tracking events (because the agent needs to know what is done and what is pending), edits and their results (because destroying the chain of file modifications means the agent will re-examine or re-modify files it already handled), and error observations (because errors are often the most informationally dense events in a session — they tell the agent what does *not* work, which narrows the search space more efficiently than successes).

### Observation masking

One of the best lessons from real agent execution is that observations are often the biggest token sink.

Terminal output, long logs, repetitive inspection results, and tool observations can consume huge amounts of context while adding very little fresh reasoning value on repeated reads.

Observation masking attacks that problem directly by preserving the event structure while hiding the bulk of low-value content behind masked placeholders.

That is a much more elegant move than deleting the event entirely, because the model still sees that something happened. The agent's reasoning about its trajectory stays intact. It knows it ran a command and got output. It just does not need to re-read 4,000 lines of terminal output from twelve iterations ago.

In practice, older observations outside the attention window are replaced with a masked placeholder. The masking threshold is configurable — you can tune how many recent observations stay fully visible versus how many get masked. That tuning matters because different tasks have different observation profiles. A task heavy on file reading needs more observation visibility than one heavy on shell commands.

### Amortized pruning

This strategy trims older history in a more controlled way, keeping head and tail structure while pruning the middle when needed.

That is useful when the oldest context contains foundational intent and the newest context contains active work, but the middle has accumulated too much operational noise.

The name change from "forgetting" to "pruning" was deliberate. The original name was honest about what was happening: the system was choosing to forget. But "forgetting" carries a passive connotation, as if the system had a limitation. "Pruning" is active. You prune because you are maintaining a shape, not because you cannot hold the weight.

The implementation only fires once history grows beyond a `max_size`, then cuts back toward roughly half that size. That amortized shape matters because a compactor that triggers on every step becomes its own performance problem — the system spends more time managing its own memory than doing useful work.

### Structured summary compaction

This approach extracts important state into structured summaries: goals, completed work, remaining tasks, important files, failures, and other stateful markers.

This is powerful, but it also taught me a cautionary lesson: summaries can preserve information while still weakening the model's operational grip if they become too abstract.

The current implementation is much stricter than a free-form summary paragraph. It uses function calling with a structured schema that requires fields for original objective, completed tasks, pending tasks, current state, files modified, test status, and dependencies. Critically, it includes a hard instruction that the original user objective must be preserved verbatim at the top. That constraint exists because I watched too many summaries slowly dilute the actual goal until the agent was confidently working on a subtly different problem than the one the user asked about.

There is a reason this strategy requires function calling support. Without it, the model generates free-form text that looks like a summary but lacks structural guarantees. The structured schema forces the model to commit to specific fields: "what was the objective?" "what is done?" "what is pending?" "what failed?" That turns a vague narrative summary into something closer to a checkpoint state that the agent can actually reason from.

### Smart compaction

This was one of the more ambitious directions: try to score importance and preserve the most valuable events more intelligently.

That matters because not all events deserve equal survival.
Some errors matter more than some successes.
Some tool outputs matter more than a lot of surrounding chatter.

This is where the subsystem got closest to research code. The smart compactor scores event importance with an LLM when available, falls back to heuristics when not, adds a recency bonus for recent events, anchors the first user message and task-tracking events and critical errors, and even reads the active plan from disk so it knows which tasks are still in flight. That is not just summarization. That is trying to make importance selection a first-class systems problem.

The heuristic fallback is worth noting because it exposes what I learned about importance when the LLM is not available to judge. Errors get a baseline importance boost because they narrow the solution space. User messages get high importance because they contain intent. Task-tracking events get anchored because they represent the agent's own understanding of its progress. File writes get preserved because they represent actual changes to the world. The heuristics are obviously less nuanced than LLM scoring, but they encode the patterns I observed watching hundreds of sessions: the events that matter most are the ones that changed something or constrained something.

### Auto-compaction

Eventually, the system needed a layer that could choose between strategies instead of pretending one strategy should always win.

That is what auto-compaction does: it acts as a selector based on session shape and practical need.

That is closer to how production systems actually need to behave.

The selector logic is explicit. Small session: no-op. Error-heavy session: recent events. Very long session with function calling available: structured summary. Very long session without that: smart or amortized pruning. Mid-sized session drowning in observation noise: masking. That logic is one of the most production-shaped parts of the subsystem because it admits that session shape should change policy.

### Pipeline compaction

Pipeline compaction is the composition layer.

The compactor pipeline chains multiple strategies sequentially and stops on the first one that produces a real compaction. I count it as real architecture, not a footnote, because composition turned out to be one of the key lessons of this entire subsystem: sometimes the right answer is not a single heroic strategy but a staged reduction.

---

## Why I Trimmed the System Back

A few weeks before writing this, I reduced the compaction system.

That may sound contradictory after everything I just said.
It is not.

The lesson was not "more strategies forever."
The lesson was: experiment deeply, learn the shape of the problem, then keep what remains clean and useful.

There is a point where a context system can become too clever for its own good.

More strategies can mean:

- more maintenance
- more ambiguity in behavior
- harder debugging
- more opportunities for the wrong strategy to fire
- more architectural noise around a subsystem that is supposed to improve clarity

So I trimmed it back to keep the agent's context system sharper and cleaner.

That mirrors a broader pattern across Grinta: I let the system explore complexity, but I do not let it keep complexity unless it earns its keep.

---

## Context Decay Is Not Just a Technical Limit

One of the most important ideas in this entire chapter is this:

**Context decay is not only a token limit problem. It is an intelligence quality problem.**

A model can be given more and still understand less if the context is saturated with the wrong kind of information.

That means context engineering is partly about subtraction.

Not because less is always better.
Because signal quality matters more than raw volume.

This is also why some removed systems in Grinta, like prompt optimization and ACE-style self-improving context work, became dangerous when they caused context pollution. A system can become more sophisticated on paper while making the model less clear in practice.

That is a brutal but valuable lesson.

---

## What This Taught Me About Agent Design

The context war taught me several things that I now consider foundational.

### 1. There is no universal memory strategy

Different tasks need different retention logic.

### 2. Observations are often the real enemy

Not because they are useless, but because they are verbose and easy to over-preserve.

### 3. Summaries are powerful but dangerous

A summary that loses operational detail can make the model confidently stupid.

### 4. Selection matters as much as compression

Choosing what to keep is more important than simply making things shorter.

### 5. Clean architecture matters here too

A messy compaction system can become another source of cognitive pollution for the developers maintaining it.

That is also why several later chapters had to split off from this one instead of being crushed into it. [13. The Hidden Playbooks](13-the-hidden-playbooks.md) is about timely expertise injection so the model is not starved of the right knowledge. [14. The Verification Tax](14-the-verification-tax.md) is about proving the system actually did the work after a long run. [15. Prompts Are Programs](15-prompts-are-programs.md) is about keeping the base instruction layer lean enough that context management does not collapse into prompt sludge.

---

## Why This Chapter Matters

This chapter matters because a lot of agent discussions talk about long context as if it were mainly a model capability issue.

It is not.

It is a systems problem.

When [08. The First Fixed Issue](08-the-first-fixed-issue.md) talks about context-window pressure as one of the ways an agent gets trapped in loops, this chapter is the deeper systems explanation underneath that symptom.

A serious agent does not stay coherent across long sessions just because the model has a large window. It stays coherent because the surrounding system actively shapes what the model sees, what it remembers, and what it is protected from drowning in.

That is what the context war forced me to learn.

---

## What Comes Next

By this point, Grinta had already been shaped by two forces:

- the things I built and removed
- the things I built and kept

But none of that happened in a vacuum.

I was studying the giants the whole time.
Not worshipping them, not copying them blindly, but learning from the patterns they revealed.

The next chapter is about those systems: what they get right, what they optimize for, and where Grinta deliberately chose a different path.

---

← [The Architectural Gauntlet](03-the-architectural-gauntlet.md) | [The Book of Grinta](BOOK_OF_GRINTA.md) | [The Giants' Playbook](05-the-giants-playbook.md) →
