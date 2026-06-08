"""Analyze session log for TUI freeze patterns."""
import json
from datetime import datetime
from pathlib import Path

from dateutil import parser

LOG = Path(
    r"logs/workspaces/New_folder__c935f63f8898/sessions/"
    r"c3a78dbc-4d7c-43-fc40eaa1c0d75c8/app.log"
)
OUT = Path("_log_analysis.txt")


def parse_ts(s: str | None):
    if not s:
        return None
    try:
        if "T" in s:
            return parser.isoparse(s)
        return datetime.strptime(s.split(",")[0], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def main() -> None:
    lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    chunks: list[tuple] = []
    tui_polls: list[tuple] = []
    file_writes: list[tuple] = []
    dropped: list[tuple] = []
    streaming_dbg: list[tuple] = []
    drain_msgs: list[tuple] = []

    for i, line in enumerate(lines, 1):
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = o.get("message", "")
        ts = parse_ts(o.get("timestamp") or o.get("asctime"))
        if not ts:
            continue
        if "StreamingChunkAction" in msg and "on_event received" in msg:
            chunks.append((ts, i, msg))
        if "[TUI] _dispatch_to_agent: poll #" in msg:
            tui_polls.append((ts, i, msg))
        if any(k in msg for k in ("FileWrite", "FileEdit", "FileRead")):
            file_writes.append((ts, i, msg[:140]))
        if "dropped" in msg.lower() or "backlogged" in msg.lower():
            dropped.append((ts, i, msg))
        if "[streaming-dbg]" in msg:
            streaming_dbg.append((ts, i, msg))
        if "RendererDrain" in msg or "drain_events" in msg:
            drain_msgs.append((ts, i, msg))

    with OUT.open("w", encoding="utf-8") as out:
        out.write(f"total_lines={len(lines)}\n")
        out.write(
            f"chunks={len(chunks)} tui_polls={len(tui_polls)} "
            f"file_events={len(file_writes)} dropped={len(dropped)} "
            f"streaming_dbg={len(streaming_dbg)}\n\n"
        )

        if len(chunks) > 1:
            deltas = [
                (chunks[j][0] - chunks[j - 1][0]).total_seconds()
                for j in range(1, len(chunks))
            ]
            deltas_sorted = sorted(deltas)
            out.write(
                "chunk delta sec: "
                f"min={deltas_sorted[0]:.3f} "
                f"p50={deltas_sorted[len(deltas_sorted) // 2]:.3f} "
                f"p95={deltas_sorted[int(len(deltas_sorted) * 0.95)]:.3f} "
                f"max={max(deltas):.3f} "
                f"mean={sum(deltas) / len(deltas):.3f}\n"
            )
            big = [
                (d, chunks[j - 1], chunks[j])
                for j, d in enumerate(deltas, 1)
                if d >= 3
            ]
            out.write(f"chunk gaps >=3s: {len(big)}\n")
            for d, prev, cur in sorted(big, reverse=True)[:40]:
                prev_id = prev[2].split("id=")[1].split(")")[0]
                cur_id = cur[2].split("id=")[1].split(")")[0]
                out.write(
                    f"  {d:.1f}s L{prev[1]}->{cur[1]} ids {prev_id}->{cur_id}\n"
                )

        out.write("\n=== Dense chunk windows (100 chunks, step 50) ===\n")
        for start in range(0, max(1, len(chunks) - 100), 50):
            window = chunks[start : start + 100]
            if len(window) < 2:
                continue
            span = (window[-1][0] - window[0][0]).total_seconds()
            polls_in = [
                p for p in tui_polls if window[0][0] <= p[0] <= window[-1][0]
            ]
            out.write(
                f"chunks[{start}:{start + 100}]: span={span:.1f}s "
                f"polls={len(polls_in)} "
                f"rate={100 / span if span else 0:.1f} chunks/s\n"
            )

        out.write("\n=== TUI poll gaps >= 10s ===\n")
        for j in range(1, len(tui_polls)):
            d = (tui_polls[j][0] - tui_polls[j - 1][0]).total_seconds()
            if d >= 10:
                out.write(
                    f"  {d:.1f}s L{tui_polls[j-1][1]}->{tui_polls[j][1]} "
                    f"{tui_polls[j-1][2]}\n"
                )

        out.write("\n=== dropped/backlog ===\n")
        for x in dropped:
            out.write(f"{x}\n")

        out.write("\n=== context around biggest chunk gap ===\n")
        if chunks:
            # find biggest gap line
            best = None
            for j in range(1, len(chunks)):
                d = (chunks[j][0] - chunks[j - 1][0]).total_seconds()
                if best is None or d > best[0]:
                    best = (d, chunks[j - 1][1], chunks[j][1])
            if best:
                lo, hi = best[1] - 20, best[2] + 20
                for i, line in enumerate(lines, 1):
                    if lo <= i <= hi:
                        try:
                            o = json.loads(line)
                            out.write(f"L{i} {o.get('message','')[:160]}\n")
                        except json.JSONDecodeError:
                            pass

    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
