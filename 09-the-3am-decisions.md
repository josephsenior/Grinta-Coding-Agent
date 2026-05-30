# 09. The 3 AM Decisions

Solo engineering has a loneliness you do not read about in startup blogs. It is not the loneliness of working alone in a room. It is the loneliness of consequence.

Once a system has enough moving parts, you eventually hit the moment when a foundational architectural decision turns out to be wrong.

For me, that reckoning usually arrived around 3 AM.

Sometimes it was the event sourcing system deadlocking because the write-ahead log was competing with the state reader. Sometimes it was realizing the multi-agent orchestration layer was scaling token cost exponentially without a matching increase in reliability. Sometimes it was recognizing that the cloud SaaS architecture was suffocating the core value of the tool.

When you are on a team, you have a meeting. You write a design doc. You argue about trade-offs. You share the blame.

When you are alone, you just stare at the screen and realize you have to burn down three weeks of your own work. And you are the only person who can do it.

---

## The Architecture of Doubt

Grinta is heavily decomposed. Twenty-one orchestration services. A context subsystem with multiple compactor implementations. A persistent event store.

That kind of decomposition is great for maintaining a mental model of the system once it is built. It is terrifying while you are building it, because for a long time, nothing works.

When you tear apart a monolithic agent loop to introduce a pub/sub event router and dedicated worker threads, the agent stops being able to complete a simple "hello world" task. For days. Sometimes weeks. You find yourself writing mock after mock just to prove that signals are moving across boundaries correctly.

During those stretches, the doubt is physical.

*Did I ruin it? Was the 1,900-line monolith actually better? Am I over-engineering this because I read too many system design books, or because the agent actually needs this isolation to scale?*

In a solo project, there is no senior engineer to tell you to keep going. There is only the Git history showing how far you have strayed from a working `main` branch.

## The Deadlock That Almost Ended It

I remember the night the persistence layer finally broke me.

I wanted durable execution. If you closed your laptop, or the power died, or the LLM provider threw a 502, I wanted you to be able to restart the agent and have it pick up exactly where it left off. That meant event sourcing.

I built a Write-Ahead Log (WAL). I moved database writes to a dedicated background thread so they wouldn't block the LLM network calls. It was beautifully asynchronous.

Then the deadlocks started.

Under high concurrency — when the agent was rapidly firing tool outputs, the LLM was streaming chunks, and the UI was requesting state snapshots — the database would lock. The whole system would freeze. No error messages. Just silence.

At 3 AM, debugging a threaded SQLite deadlock in an asynchronous Python application is miserable on its own. Doing it while the system is also holding open a WebSocket connection and streaming an LLM response makes you question your life choices.

The fix wasn't more complexity. The fix was less. I had to rip out the overly clever async queuing and accept that sometimes, a synchronous, blocking write with a timeout is exactly what you need to guarantee atomic state evolution. I stripped the cleverness out of the `LocalFileStore`. I relied on `os.replace` for atomic file updates. I embraced boring engineering.

The SQLite accelerator that survived that reckoning is deliberately conservative. It runs in WAL mode — Write-Ahead Logging at the database level, not to be confused with the application-level WAL — which allows concurrent reads while writes proceed. It maintains a separate read connection from the write connection, which eliminates the lock contention that killed the earlier design. Write batching groups multiple events into single transactions. Read caching avoids redundant queries for the same event range.

What makes it work is what it does *not* do. It does not try to be asynchronous. It does not use background threads for writes. It does not attempt concurrent write access. Every write goes through a single synchronous path, and every read goes through a separate connection that never competes for write locks. The design is almost embarrassingly simple compared to the async queuing system it replaced, and that simplicity is exactly why it has never deadlocked since.

The event persistence layer built on top of this implements its own application-level Write-Ahead Log for crash recovery. Before committing events to the main store, it writes a checkpoint to a separate WAL file. If the process crashes mid-write, the next startup reads the WAL, finds uncommitted events, and replays them.

The recovery logic classifies checkpoints into four states: clean (nothing to recover), blocked with uncommitted events (replay needed), stale (WAL too old, discard), and corrupt (WAL unparseable, discard and warn). That classification was born from testing every crash scenario I could simulate — kill -9 during write, power loss during flush, disk-full during checkpoint.

The critical event classification adds another layer. Not all events are equally important for crash recovery. The persistence layer tags certain action types as critical: `change_agent_state`, `finish`, and `reject`. These three actions change the fundamental state of the session. If they are lost in a crash, the session resumes in a state that contradicts what actually happened — the agent thinks it is still running when it already finished, or vice versa. Critical events get flushed to disk immediately rather than batched.

### The Pub/Sub System That Made it Survivable

The event stream underneath the persistence layer is a pub/sub system with typed subscribers.

Every component that needs to react to events — the agent controller, the CLI display, the server layer, the runtime, the memory manager — registers as a typed subscriber. When an event fires, the stream routes it to all registered subscribers. The subscriber types are enumerated: `AGENT_CONTROLLER`, `CLI`, `SERVER`, `RUNTIME`, `MEMORY`, `MAIN`, `TEST`.

This matters because without typed pub/sub, every component that needed to observe agent events had to be hard-wired into the orchestration loop. Adding the CLI display meant modifying the controller. Adding telemetry meant modifying the controller. Adding the memory manager meant modifying the controller. The controller became a dependency magnet.

With pub/sub, the controller publishes events into the stream and does not know or care who is listening. The CLI subscribes to display events. The memory manager subscribes to condensation triggers. The test harness subscribes to assertions. They are all decoupled from each other and from the controller.

That separation is why I could rip out the WebSocket server layer without touching the agent loop at all. The server was just another subscriber. Removing it was removing a subscription, not restructuring the core.

## Cutting the Heavy Lifting

The hardest decisions were not the technical fixes. They were the product cuts.

I have already talked about killing the SaaS fortress and the multi-agent swarm. But the *moment* of killing them is what this chapter is about.

I had spent a week perfecting the Docker container pooling. The `WarmRuntimePool` was working. Containers were recycling perfectly. Telemetry was flowing.

And then I looked at how much friction it added for a developer who just wanted Grinta to fix a bug in their local clone of a repository. To use my beautiful container pool, they would have to sync their local file state to the cloud container, run the agent, and sync the results back. Or I would have to build a local Docker-in-Docker orchestrator.

Sitting there, staring at thousands of lines of pristine volume-mounting code, I had to admit the truth: I built it for me, not for them. I built it because building distributed systems is fun.

I opened the directory. I highlighted the files. I pressed delete.

I didn't deprecate it. I didn't hide it behind a feature flag. I just deleted it.

In solo engineering, your biggest enemy is not technical debt. It is emotional debt—the reluctance to delete something you worked hard on, even when you know it is holding the product back.

## The Payoff

You make those 3 AM decisions because you have to.

But there is a payoff.

When you are the only one making the cuts, the resulting system reflects a single, coherent vision. Grinta does not have design-by-committee compromises. It does not have two features that do the same thing because two different teams couldn't agree.

It has scars. It has clear boundaries. It has an architecture shaped by the painful realization of what happens when you let complexity win.

The loneliness of solo engineering is real. So is the uncompromising clarity that comes out the other side.

---

← [The First Fixed Issue](08-the-first-fixed-issue.md) | [The Book of Grinta](README.md) | [The Model-Agnostic Reckoning](10-model-agnostic-reckoning.md) →
