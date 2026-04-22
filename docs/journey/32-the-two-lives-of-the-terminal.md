# 31. The Two Lives of the Terminal

I did not go back in time to erase [chapter 11](11-the-console-wars.md). That would miss the point of how this project grows. The “Console Wars” are still the truth: Windows and Unix disagree about what a process even *is*, tmux is still the gold standard where it exists, and the three implementation tiers (tmux bash, simple bash, PowerShell) are still the map most commands follow every day.

What changed is that I finally closed a gap I had been carrying in the back of my mind since the research month in September 2025, when I wrote down that other agents lean on **PTY-based** terminal behavior. I had the abstraction (`UnifiedShellSession`, persistent sessions, the `terminal_manager` tool) before I had a *local* answer that did not depend on Docker, did not require tmux to exist, and did not give up the moment you are on native Windows PowerShell or on Linux without a multiplexer.

This chapter is the addendum. It does not replace the old decisions. It layers a new one on top, with the same honesty: nothing here is “solved forever,” and some of it is deliberately conservative.

---

## The Gap Chapter 11 Left Open

In the Console Wars story, the fallback path was honest: **subprocess** execution, `nohup` for background, **no reliable interactive I/O** on the paths that are not tmux. That is not a cosmetic limitation. A developer on Windows running the agent against a real repo still needs to start a dev server, see the prompt, answer a TUI, resize a curses app, or send Ctrl-C to something that is not a one-shot `npm test`. If the only answer is “install tmux” or “use WSL,” you are smuggling a platform requirement through the back door.

I refused to make Docker mandatory for “real terminal” behavior. The whole pivot of this project is local, honest, runs on a laptop. So the missing piece was always: a **native** pseudo-terminal on each OS. On Unix family systems that means a PTY. On Windows 10+ that means the same *idea* (ConPTY), exposed through a small dependency (`pywinpty` on Windows, `ptyprocess` elsewhere) so that Python can own the child and the stream without pretending the world is all POSIX.

No multiplexer. No `libtmux` for this path. A deliberately small primitive: spawn, read, write, resize, lifecycle. Then an adapter that implements the same `read_output` / `write_input` contract the rest of the runtime already expected.

That is the implementation story, and I am not going to drown you in file names. What matters in *this* book is the **decision** that comes after you have the primitive.

---

## Two Speeds, On Purpose

Once you *can* put every shell behind a PTY, the seductive next step is to flip the default: make the “main” session interactive too, so the agent always has a TTY, always feels like a human terminal.

I decided **not** to do that — at least not as the default, and not without a long bake-in.

The boring session that runs `execute_bash` / `execute_powershell` (or the tmux `BashSession` when the stars align) is still the spine for the work that has to be **predictable**: one command, one exit code for the contract, bounded output, fewer moving parts, fewer ways for a prompt regex to miss and stall the whole loop. The agent’s everyday loop is still: run tests, run linters, install packages, run git. That is subprocess and PS1-structured batch semantics, not a perpetual REPL.

The **new** path is the second life: `terminal_manager` (and the sessions it opens) can bind to a PTY-backed implementation when the user needs a **long-lived, interactive** shell — the kind that behaves like a real terminal for servers, wizards, and anything that is not a single fire-and-forget line.

So Grinta’s terminal is not *one* thing anymore, in a conceptual sense. It is **two speeds**:

1. **Batch / default** — what chapter 11 described: reliability and cross-platform policy first, interactive input only where the stack already supported it (tmux).
2. **Interactive / opt-in** — the PTY path, OS-agnostic, no Docker, wired through the same session manager ideas, with explicit knobs for resize and control when we needed them (because an interactive terminal that cannot resize or send Ctrl-C is only half a terminal).

That split is a product decision as much as an engineering one. I would rather have an honest “two modes” model than a single PTY default that makes every `pytest` run depend on prompt timing and buffer growth before we have the miles on the tires.

If we ever make the default session PTY-backed, it should be behind a **flag** and a lot of green CI time — not a quiet swap because the new primitive exists.

---

## What “Honest” Means for Metadata

The tmux path already had a trick I believed in: a structured prompt tail (`###PS1JSON###` …) so the runtime can read **exit code** and **working directory** from the shell’s own report, not from guessing. The PTY adapter for bash can now participate in the same contract **when** it is running bash: install the same idea of PS1, wait for a new block after a command, parse the last JSON chunk. It is not magic on PowerShell yet — the world is not that fair — and I am not going to claim parity where we did not build it. Growth includes saying “good enough for bash in the PTY path, best-effort elsewhere until someone pays the tax for a PowerShell prompt function that emits the same shape.”

That is the same discipline as the rest of the book: **reliability over pretending.**

---

## The Agent Still Has to Be Taught the Story

A final honest note, because this journey is not marketing.

The **tool** definitions (`terminal_manager`, parameters for open/input/read) carry part of the truth. The **system prompt** does not yet hold the reader’s hand through “when to use the manager versus the default shell tool” the way the routing ladder does for file operations. I am comfortable documenting that here: implementation can run ahead of the narrative the model sees every turn. Closing that gap is prompt and routing work, not a second PTY. The decision in this chapter stands either way: two speeds in the engine; one story we still need to teach the LLM in plain language.

---

## Why I Wrote It This Way

I kept chapter 11. I added this one. The older me chose tmux, fallbacks, and the semantic shell. The current me added native PTY sessions without Docker, split default from interactive on purpose, and tied bash metadata to the same JSON PS1 idea where it fits.

If you are reading the chapters in order, you might feel a tension between “one unified abstraction” and “two lives.” The tension is real. The resolution is: **one abstraction, multiple implementations, two** *product* *postures* — batch reliability first, interactive truth when the user’s task demands it.

That is not retreating from the console wars. It is surviving them without lying to the user about what each path can guarantee.

---

← [The Myth of the Committee](31-the-myth-of-the-committee.md) | [The Book of Grinta](README.md) | [The Road Ahead](07-the-road-ahead.md) →
