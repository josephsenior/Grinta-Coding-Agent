# Windows and WSL

Grinta runs on **native Windows** (PowerShell, Git Bash) and on **WSL/Linux**. These are different runtimes — not interchangeable installs.

## Pick your runtime

| You open… | Grinta runs as… | Install Grinta where? |
| --- | --- | --- |
| **PowerShell** or **cmd** on Windows | Windows (PowerShell shell tool by default unless configured) | Windows (`pipx`, Scoop, or `uv` on Windows) |
| **Git Bash** on Windows | Windows (bash shell tool; see `windows_shell` below) | Windows — same install as above |
| **Ubuntu / WSL** terminal | **Linux** (full bash, tmux, Linux paths) | **Inside WSL** — separate `pipx` / `uv` install |

**Rule:** A Windows `pipx install grinta-ai` does **not** put `grinta` on PATH in WSL. If you open an Ubuntu terminal and see `grinta: command not found`, install Grinta **inside WSL** (see below).

---

## Native Windows (PowerShell · Git Bash)

### Install (once, on Windows)

```powershell
pipx install grinta-ai
cd C:\path\to\your\project
grinta
```

First run runs setup automatically. Optional: `grinta init` to reconfigure without the TUI.

Dev checkout instead:

```bash
bash start_here.sh
```

(`START_HERE.ps1` on native Windows PowerShell.) Installs `uv` and Python 3.12 automatically when missing.

### Default shell for the agent

In `settings.json` (or `~/.grinta/settings.json` for pipx installs):

```json
"security": {
  "windows_shell": "bash"
}
```

| Value | Agent uses |
| --- | --- |
| `bash` (default) | `execute_bash` via Git Bash when available |
| `powershell` | `execute_powershell` |

Override via env only if needed: `SECURITY_WINDOWS_SHELL=powershell`. Secrets stay in `.env`; this belongs in `settings.json`. See [SETTINGS.md](SETTINGS.md).

### Run on a project

```bash
cd C:\path\to\project
grinta
```

From Git Bash, use Windows-style paths or forward slashes.

---

## WSL / Ubuntu (Linux inside Windows)

WSL is a **real Linux environment**. Grinta must be installed **there**, not reused from Windows.

### 1. Install WSL (once, on Windows)

PowerShell (Admin):

```powershell
wsl --install -d Ubuntu
```

List distros: `wsl -l -v`

### 2. Install Grinta inside WSL (once, in Ubuntu)

Open **Ubuntu** (Start menu or Windows Terminal → Ubuntu):

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv pipx
pipx ensurepath && source ~/.bashrc

pipx install grinta-ai
cd "/mnt/c/Users/you/Desktop/your-project"
grinta
```

First run runs setup automatically.

Dev checkout (installs `uv` + Python 3.12 automatically when missing):

```bash
cd ~/Grinta   # clone or copy repo into WSL home — faster than /mnt/c
bash start_here.sh
```

### 3. `cd` to a Windows folder from WSL

Windows paths map under `/mnt/<drive>/`:

| Windows | WSL |
| --- | --- |
| `C:\Users\you\Desktop\Grinta` | `/mnt/c/Users/you/Desktop/Grinta` |
| `C:\Users\you\Desktop\New folder` | `"/mnt/c/Users/you/Desktop/New folder"` |

Quote paths that contain spaces.

```bash
cd "/mnt/c/Users/you/Desktop/New folder"
grinta
```

Open WSL already in a folder (from PowerShell):

```powershell
wsl -d Ubuntu --cd "/mnt/c/Users/you/Desktop/New folder"
```

Replace `Ubuntu` with your distro name from `wsl -l -v`.

### 4. Settings location in WSL

Consumer pipx install: `~/.grinta/settings.json` (Linux home, not Windows `%USERPROFILE%`).

Dev checkout: `<repo>/settings.json` inside the WSL tree.

API keys: `~/.grinta/.env` or repo `.env` — same layout as Linux; still **not** mixed with the Windows install unless you copy files yourself.

### 5. Performance tip

Projects on `/mnt/c/...` work but are slower than a clone under `~/` in WSL. For daily WSL use, prefer:

```bash
git clone <url> ~/Grinta
cd ~/projects/my-app
grinta
```

---

## Common mistakes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `grinta: command not found` in WSL | Installed only on Windows | `pipx install grinta-ai` **inside** Ubuntu |
| Agent uses PowerShell on Windows | `windows_shell` is `powershell` or Git Bash missing | Set `"windows_shell": "bash"` in `settings.json` |
| WSL feels slow on a Windows repo | `/mnt/c` cross-filesystem I/O | Clone or copy project to `~/` in WSL |
| Two different configs | Windows and WSL each have their own `~/.grinta` | Configure each environment separately (`grinta` or `grinta init`) |

---

## Related docs

- [QUICK_START.md](QUICK_START.md) — command cheat sheet
- [INSTALL.md](INSTALL.md) — pipx, Scoop, source
- [SETTINGS.md](SETTINGS.md) — `security.windows_shell`
- [SUPPORT_MATRIX.md](SUPPORT_MATRIX.md) — platform parity (tmux, sandbox, etc.)
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — other failures
