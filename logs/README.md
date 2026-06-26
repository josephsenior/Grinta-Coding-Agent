# Grinta logs

All runtime logs live here — **same folder as `backend/`**, never inside your open project.

| Path | What it is |
|------|------------|
| `launch.log` | One line appended every time you run `grinta` or `start_here.sh` |
| `workspaces/<name>/sessions/<id>/session.jsonl` | Full session event log |
| `workspaces/<name>/sessions/<id>/session.audit.txt` | Human-readable session summary (on exit) |

**WSL:** if you run Grinta from `~/Grinta`, logs are in `/home/<you>/Grinta/logs/` — not on the Windows Desktop copy unless you launch from there.

Quick check:

```bash
ls -la logs/
tail logs/launch.log
find logs/workspaces -name session.jsonl 2>/dev/null | tail
```
