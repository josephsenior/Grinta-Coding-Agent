# Windows and WSL

**Windows install ≠ WSL install.** `pipx install` on Windows does not put `grinta` in an Ubuntu terminal.

## Native Windows

```powershell
pipx install grinta-ai
grinta
```

Dev: `.\START_HERE.ps1` (installs `uv` + Python if missing).

Default agent shell is bash (`execute_bash`). To use PowerShell instead, in `settings.json`:

```json
"security": { "windows_shell": "powershell" }
```

## WSL

Install **inside** Ubuntu:

```bash
sudo apt install -y python3.12 python3.12-venv pipx
pipx ensurepath && source ~/.bashrc
pipx install grinta-ai
```

Open a Windows folder: `C:\Users\you\project` → `cd "/mnt/c/Users/you/project"`

Dev: `bash start_here.sh` in the repo (prefer `~/` over `/mnt/c/` for speed).

Settings: `~/.grinta/` in WSL — separate from Windows `%USERPROFILE%\.grinta`.
