# GA onboarding gate

**Not ready for GA sign-off.**

Need **3× interactive pipx** + **3× interactive source** on fresh VMs (no prior `~/.grinta`). File reports here using [REPORT_TEMPLATE.md](REPORT_TEMPLATE.md). CI smoke ≠ interactive GA.

| Path | Interactive filed | CI smoke filed | Notes |
| --- | --- | --- | --- |
| pipx Linux | 0 | 0 | CI wheel smoke only until interactive reports land |
| pipx Windows | 0 | 0 | Partial interactive evidence acceptable while collecting 3× |
| pipx WSL2 | 0 | 0 | Run `scripts/smoke/smoke_wsl_layout.sh` inside Ubuntu; manual GA |
| source Linux | 0 | 0 | CI only until interactive reports land |
| source Windows | 0 | 1 | Contributor smoke + interactive reports |
| source WSL2 | 0 | 0 | clone on Linux home, project on `/mnt/c`; `grinta doctor` + interrupt test |

_Last updated by `ga_onboarding_gate.py` on 2026-07-08 12:08 UTC._

See [RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md) before `v1.0.0`.
