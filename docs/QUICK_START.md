# Quick Start

Grinta is a local-first coding agent for long-running coding tasks. The current
repository is the release source of truth; a `grinta` project is not currently
published on PyPI.

## Install and launch

From the project you want Grinta to work on, run:

```bash
pipx install "git+https://github.com/josephsenior/Grinta-Coding-Agent.git"
grinta
```

The first launch guides you through provider and model setup. To configure Grinta before launching the TUI, run `grinta init`.

The Grinta package and your target project are separate: `pipx` installs the
application from GitHub in an isolated environment, while `grinta` operates on
the directory where you launch it. Quote paths that contain spaces.

To open a different target explicitly:

```bash
grinta -p "<project>"
```

## Windows, Linux, and macOS

Use the same two-command install in PowerShell or a POSIX shell:

```bash
pipx install "git+https://github.com/josephsenior/Grinta-Coding-Agent.git"
grinta
```

If the `grinta` command is not found after installation, run `pipx ensurepath`, restart the terminal, and try again.

## WSL (Ubuntu)

Install and run Grinta inside Ubuntu, not PowerShell. Native Windows and WSL use separate installations and settings.

Keep the target project on the Linux filesystem for best performance. A project may remain under `/mnt/c`, although filesystem operations will be slower. A Windows path such as `C:\foo\bar` becomes `/mnt/c/foo/bar` in WSL.

If required, install the WSL prerequisites first:

```bash
sudo apt update
sudo apt install -y pipx
pipx ensurepath
pipx install "git+https://github.com/josephsenior/Grinta-Coding-Agent.git"
grinta
```

## Optional features

There are no optional extras to install. History search (`search_history`) is
built in and runs on SQLite from the Python standard library; turn it off with
`"enable_vector_memory": false` in settings if you don't want it.

## Develop from source

Editable installs are for contributors working on Grinta itself:

```bash
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git Grinta
cd Grinta
pipx install -e .
```

The full development environment and test workflow are documented in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Useful commands

| Command | Purpose |
| --- | --- |
| `grinta init` | Create or update configuration |
| `grinta doctor` | Check installation, settings, and WSL layout |
| `grinta -p "<project>"` | Open a target without changing directory |
| `grinta --help` | List CLI options |
| `grinta --version` | Show the installed version |

For installation or startup problems, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
