# Troubleshooting

Install paths: [QUICK_START.md](QUICK_START.md).

## Install

| Problem | Fix |
| --- | --- |
| `pipx` / `grinta` not found | Python 3.12+ → `pip install --user pipx` → `pipx ensurepath` → `pipx install grinta-ai` |
| `grinta` not found in WSL | Install inside Ubuntu, not Windows |
| `uv` not found (dev) | `.\START_HERE.ps1` or `bash start_here.sh` |
| Python 3.12+ (dev) | `uv python install 3.12` or re-run start script |

## Startup

- **No TUI:** stdin is not a TTY (piped/redirected) — use interactive terminal or `grinta --help`
- **Bad config:** `grinta init` or fix `settings.json` — see [SETTINGS.md](SETTINGS.md)
- **Missing key:** set `LLM_API_KEY` in `~/.grinta/.env` or repo `.env`

## LLM

| Error | Fix |
| --- | --- |
| 401 | Key must match model prefix (`openai/…`, `anthropic/…`, etc.) |
| Model not found | Use qualified ID, e.g. `openai/gpt-5.1`, `ollama/llama3.2` |
| Ollama down | `ollama serve` then `ollama pull <model>` |

## Windows

- **PowerShell instead of bash:** `"security": { "windows_shell": "bash" }` in settings (default is bash)
- **Long paths:** enable Windows long paths (registry `LongPathsEnabled=1`)

## WSL2

- **Slow startup / agent stalls:** clone on `/mnt/c` — move repo to Linux home; run `grinta doctor`
- **Wrong install:** use `pipx` inside Ubuntu, not Windows PowerShell
- **`grinta` not found in WSL:** install inside Ubuntu ([QUICK_START.md](QUICK_START.md#wsl-ubuntu))
- **Project on `/mnt/c` is slow:** expected; see [QUICK_START.md — WSL](QUICK_START.md#wsl-ubuntu)
- **tmux / shell errors:** ensure `TMUX_TMPDIR` writable; run `grinta doctor` on WSL

## Checks

```bash
grinta doctor          # full install report
grinta doctor --verbose
```

In TUI: `/health` (fast subset).

Still stuck: [SUPPORT_MATRIX.md](SUPPORT_MATRIX.md) · open an issue with command, error, OS, Python version.
