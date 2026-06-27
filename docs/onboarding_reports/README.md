# Onboarding reports (maintainers)

GA needs **3× pipx** and **3× source** fresh-machine runs on real VMs. Status: [GA_GATE_STATUS.md](GA_GATE_STATUS.md).

Template: [REPORT_TEMPLATE.md](REPORT_TEMPLATE.md). File as `YYYY-MM-DD_<path>_<os>_<n>.md`.

Smoke CI covers non-interactive paths only — interactive first `grinta` + real task must be manual.

First-task smoke: `Run /health and tell me whether git and ripgrep are detected.`
