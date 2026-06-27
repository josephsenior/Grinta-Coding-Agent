# GA onboarding gate

**Not ready for GA sign-off.**

Need **3× interactive pipx** + **3× interactive source** on fresh VMs (no prior `~/.grinta`). File reports here using [REPORT_TEMPLATE.md](REPORT_TEMPLATE.md). CI smoke ≠ interactive GA.

| Path | Interactive filed | Notes |
| --- | --- | --- |
| pipx Linux | 0 | CI wheel smoke only |
| pipx Windows | 1 partial | |
| source Linux | 0 | CI only |
| source Windows | 1 | |
| pipx WSL2 | 0 | Run `scripts/smoke/smoke_wsl_layout.sh` inside Ubuntu; manual GA |
| source WSL2 | 0 | clone on Linux home, project on `/mnt/c`; `grinta doctor` + interrupt test |

See [RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md) before `v1.0.0`.
