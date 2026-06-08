#!/usr/bin/env python3
"""Strip noisy session log lines and produce a readable audit summary."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

NOISE_PATTERNS = (
    re.compile(r"on_event received StreamingChunkAction\b"),
    re.compile(r"\[streaming-dbg\]"),
    re.compile(r"\[TUI\] _dispatch_to_agent: poll #"),
    re.compile(r"_dispatch_to_agent: \d+ consecutive polls"),
    re.compile(r"dispatching via run_or_schedule$"),
)

ISSUE_LEVELS = frozenset({"WARNING", "ERROR", "CRITICAL"})

ISSUE_MSG_PATTERNS = (
    re.compile(r"pending action timed out", re.I),
    re.compile(r"HARD TIMEOUT", re.I),
    re.compile(r"AGENT_HARD_TIMEOUT", re.I),
    re.compile(r"STALL TIMEOUT", re.I),
    re.compile(r"stuck_detection", re.I),
    re.compile(r"recover|retry|backoff", re.I),
    re.compile(r"exception|traceback|failed", re.I),
    re.compile(r"dropped while the renderer was backlogged", re.I),
    re.compile(r"Memory pressure", re.I),
    re.compile(r"circuit.?breaker", re.I),
    re.compile(r"no.step.progress", re.I),
)

STATE_RE = re.compile(
    r"Setting agent\([^)]+\) state from AgentState\.(\w+) to AgentState\.(\w+)"
)
ACTION_RE = re.compile(r"obtained action=ActionType\.(\w+)")
LLM_DONE_RE = re.compile(r"OrchestratorExecutor\.async_execute done in ([\d.]+)s")
FILE_EVENT_RE = re.compile(r"(FileWrite|FileEdit|FileRead)(Action|Observation)")


def parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        if "T" in raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return datetime.strptime(raw.split(",")[0], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def is_noise(message: str) -> bool:
    return any(p.search(message) for p in NOISE_PATTERNS)


def is_issue(level: str, message: str) -> bool:
    if level in ISSUE_LEVELS:
        return True
    return any(p.search(message) for p in ISSUE_MSG_PATTERNS)


def format_line(obj: dict) -> str:
    ts = obj.get("asctime") or obj.get("timestamp") or ""
    level = obj.get("level", "INFO")
    msg = obj.get("message", "")
    extra = []
    for key in ("msg_type", "conversation_id"):
        if key in obj and key != "message":
            extra.append(f"{key}={obj[key]}")
    suffix = f" [{', '.join(extra)}]" if extra else ""
    return f"{ts} [{level}] {msg}{suffix}"


def analyze_session(log_path: Path, stripped_path: Path, report_path: Path) -> None:
    total = 0
    kept = 0
    stripped = 0
    levels = Counter()
    issue_lines: list[str] = []
    state_transitions: list[tuple[str, str, str, int]] = []
    actions: list[tuple[str, str, int]] = []
    llm_calls: list[tuple[float, str, int]] = []
    file_events: list[tuple[str, str, int]] = []
    end_state: str | None = None
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    pending_timeouts = 0
    retries = 0
    on_event_types = Counter()

    with log_path.open(encoding="utf-8", errors="replace") as src, stripped_path.open(
        "w", encoding="utf-8"
    ) as out:
        for line_no, line in enumerate(src, 1):
            total += 1
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                out.write(f"# L{line_no} (non-json) {line}\n")
                kept += 1
                continue

            msg = obj.get("message", "")
            level = obj.get("level", "INFO")
            levels[level] += 1

            ts = parse_ts(obj.get("timestamp") or obj.get("asctime"))
            if ts:
                first_ts = first_ts or ts
                last_ts = ts

            if is_noise(msg):
                stripped += 1
                continue

            kept += 1
            out.write(format_line(obj) + "\n")

            if is_issue(level, msg):
                issue_lines.append(f"L{line_no}: {format_line(obj)}")

            m = STATE_RE.search(msg)
            if m:
                state_transitions.append((m.group(1), m.group(2), msg, line_no))
                end_state = m.group(2)

            m = ACTION_RE.search(msg)
            if m:
                actions.append((m.group(1), msg, line_no))

            m = LLM_DONE_RE.search(msg)
            if m:
                llm_calls.append((float(m.group(1)), msg, line_no))

            m = FILE_EVENT_RE.search(msg)
            if m:
                file_events.append((m.group(1) + m.group(2), msg[:120], line_no))

            if "on_event received " in msg and "StreamingChunkAction" not in msg:
                evt = msg.split("on_event received ", 1)[-1].split(" (id=", 1)[0]
                on_event_types[evt] += 1

            if re.search(r"pending action timed out", msg, re.I):
                pending_timeouts += 1
            if re.search(r"\bretry\b|\bbackoff\b|recover", msg, re.I):
                retries += 1

    duration_min = 0.0
    if first_ts and last_ts:
        duration_min = (last_ts - first_ts).total_seconds() / 60.0

    llm_times = [t for t, _, _ in llm_calls]
    slow_llm = [(t, ln, m) for t, m, ln in llm_calls if t >= 60.0]

    suspicious_states = [
        (a, b, m, ln)
        for a, b, m, ln in state_transitions
        if b in {"ERROR", "STOPPED"} or (a == "ERROR" and b != "AWAITING_USER_INPUT")
    ]

    with report_path.open("w", encoding="utf-8") as rep:
        rep.write("SESSION LOG AUDIT\n")
        rep.write("=" * 72 + "\n")
        rep.write(f"Source: {log_path}\n")
        rep.write(f"Stripped log: {stripped_path}\n")
        rep.write(f"Total lines: {total:,}\n")
        rep.write(f"Stripped (noise): {stripped:,} ({100*stripped/max(total,1):.1f}%)\n")
        rep.write(f"Kept lines: {kept:,}\n")
        if first_ts and last_ts:
            rep.write(
                f"Duration: {duration_min:.1f} min "
                f"({first_ts.isoformat()} -> {last_ts.isoformat()})\n"
            )
        rep.write(f"Final agent state: {end_state or 'unknown'}\n")
        rep.write("\n")

        rep.write("LEVEL COUNTS (all lines)\n")
        rep.write("-" * 40 + "\n")
        for lvl, cnt in levels.most_common():
            rep.write(f"  {lvl}: {cnt:,}\n")
        rep.write("\n")

        rep.write("HEALTH SIGNALS\n")
        rep.write("-" * 40 + "\n")
        rep.write(f"  Pending action timeouts: {pending_timeouts}\n")
        rep.write(f"  Retry/recovery mentions: {retries}\n")
        rep.write(f"  LLM calls completed: {len(llm_calls)}\n")
        if llm_times:
            rep.write(
                f"  LLM latency — min={min(llm_times):.1f}s "
                f"median={sorted(llm_times)[len(llm_times)//2]:.1f}s "
                f"max={max(llm_times):.1f}s\n"
            )
        rep.write(f"  File operations logged: {len(file_events)}\n")
        rep.write(f"  Agent actions obtained: {len(actions)}\n")
        rep.write("\n")

        verdict = "CLEAN"
        notes: list[str] = []
        if end_state == "FINISHED":
            notes.append("Session ended in FINISHED (success).")
        elif end_state == "AWAITING_USER_INPUT":
            notes.append("Session ended awaiting user input (normal idle).")
        elif end_state in {"ERROR", "STOPPED"}:
            verdict = "ISSUES FOUND"
            notes.append(f"Session ended in {end_state}.")

        if pending_timeouts:
            verdict = "ISSUES FOUND"
            notes.append(f"{pending_timeouts} pending-action timeout(s) detected.")
        if suspicious_states:
            verdict = "ISSUES FOUND"
            notes.append(f"{len(suspicious_states)} error/stop state transition(s).")

        warn_count = levels.get("WARNING", 0)
        err_count = levels.get("ERROR", 0) + levels.get("CRITICAL", 0)
        if err_count:
            verdict = "ISSUES FOUND"
            notes.append(f"{err_count} ERROR/CRITICAL log line(s).")
        elif warn_count and warn_count <= 5:
            notes.append(f"{warn_count} WARNING(s) — review below (may be benign).")
        elif warn_count:
            verdict = "REVIEW"
            notes.append(f"{warn_count} WARNING(s) — worth scanning.")

        rep.write(f"VERDICT: {verdict}\n")
        for note in notes:
            rep.write(f"  • {note}\n")
        rep.write("\n")

        if issue_lines:
            rep.write(f"ISSUES / WARNINGS ({len(issue_lines)} lines)\n")
            rep.write("-" * 40 + "\n")
            for item in issue_lines[:200]:
                rep.write(item + "\n")
            if len(issue_lines) > 200:
                rep.write(f"... and {len(issue_lines) - 200} more\n")
            rep.write("\n")

        if suspicious_states:
            rep.write("SUSPICIOUS STATE TRANSITIONS\n")
            rep.write("-" * 40 + "\n")
            for a, b, m, ln in suspicious_states:
                rep.write(f"L{ln}: {a} -> {b}\n")
            rep.write("\n")

        if slow_llm:
            rep.write(f"SLOW LLM CALLS (>=60s) — {len(slow_llm)}\n")
            rep.write("-" * 40 + "\n")
            for t, ln, m in sorted(slow_llm, reverse=True)[:30]:
                rep.write(f"L{ln}: {t:.1f}s\n")
            rep.write("\n")

        rep.write("STATE TRANSITION TIMELINE (deduped consecutive)\n")
        rep.write("-" * 40 + "\n")
        last_pair = None
        for a, b, _, ln in state_transitions:
            pair = (a, b)
            if pair != last_pair:
                rep.write(f"L{ln}: {a} -> {b}\n")
                last_pair = pair
        rep.write("\n")

        rep.write("TOP NON-CHUNK EVENT TYPES\n")
        rep.write("-" * 40 + "\n")
        for evt, cnt in on_event_types.most_common(25):
            rep.write(f"  {cnt:5d}  {evt}\n")
        rep.write("\n")

        rep.write("ACTION TYPE BREAKDOWN\n")
        rep.write("-" * 40 + "\n")
        action_counts = Counter(a for a, _, _ in actions)
        for act, cnt in action_counts.most_common():
            rep.write(f"  {cnt:4d}  {act}\n")
        rep.write("\n")

        if file_events:
            rep.write(f"FILE EVENTS (first 40 of {len(file_events)})\n")
            rep.write("-" * 40 + "\n")
            for kind, msg, ln in file_events[:40]:
                rep.write(f"L{ln} [{kind}] {msg}\n")
            rep.write("\n")

    print(f"Wrote stripped log: {stripped_path} ({kept:,} lines)")
    print(f"Wrote audit report: {report_path}")
    print(f"Verdict: {verdict}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_path", type=Path)
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for stripped log and report (default: same as log)",
    )
    args = parser.parse_args()

    log_path = args.log_path.resolve()
    out_dir = (args.output_dir or log_path.parent).resolve()
    stem = log_path.stem
    stripped_path = out_dir / f"{stem}.stripped.log"
    report_path = out_dir / f"{stem}.audit.txt"
    analyze_session(log_path, stripped_path, report_path)


if __name__ == "__main__":
    main()
