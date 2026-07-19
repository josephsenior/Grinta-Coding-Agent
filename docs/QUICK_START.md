# Quick Start

Grinta is currently distributed from source. A public GitHub release and PyPI package have not been published yet.

The Grinta checkout and the project you want the agent to work on are different folders:

- `Grinta` is this repository and contains the runtime and settings.
- `<project>` is the repository or folder you want Grinta to modify.

Quote paths that contain spaces. Native Windows and WSL use separate installations and settings.

## Fastest supported install

### Windows PowerShell

```powershell
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git Grinta
cd Grinta
.\START_HERE.ps1
```

The bootstrap installs the supported Python toolchain, synchronizes dependencies, runs the setup wizard and health checks, and installs the `grinta` command from the checkout.

Then open the project you want Grinta to work on:

```powershell
cd "<project>"
grinta
```

### Linux, macOS, or WSL

```bash
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git ~/Grinta
cd ~/Grinta
bash start_here.sh
pipx install -e .
```

Then:

```bash
cd "<project>"
grinta
```

If you prefer not to install a global command, run from any project with:

```bash
cd "<project>"
uv run --directory ~/Grinta grinta -p "$(pwd)"
```

## WSL notes

Install and run Grinta inside Ubuntu, not PowerShell. Keep the Grinta checkout on the Linux filesystem for best performance:

```bash
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git ~/Grinta
```

Your target project may remain under `/mnt/c`, although filesystem operations will be slower. A Windows path such as `C:\foo\bar` becomes `/mnt/c/foo/bar` in WSL.

If required, install the basic WSL prerequisites first:

```bash
sudo apt update
sudo apt install -y git pipx tmux
pipx ensurepath
```

## Run directly from the checkout

After bootstrap, you can avoid a global installation:

```bash
cd "<project>"
uv run --directory /path/to/Grinta grinta -p "$(pwd)"
```

Or provide the target explicitly:

```bash
uv run --directory /path/to/Grinta grinta -p "<project>"
```

On Windows PowerShell:

```powershell
uv run --directory C:\path\to\Grinta grinta -p "C:\path\to\project"
```

## Optional features

Install optional dependencies from the same checkout:

```bash
pipx install -e ".[rag]"       # vector-memory support
pipx install -e ".[browser]"   # browser tools
pipx install -e ".[all]"       # all optional integrations
```

## Useful commands

| Command | Purpose |
|---|---|
| `grinta init` | Create or update configuration |
| `grinta doctor` | Check installation, settings, and WSL layout |
| `grinta -p "<project>"` | Open a target without changing directory |
| `grinta --help` | List CLI options |
| `grinta --version` | Show the current source version |

For installation or startup problems, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
