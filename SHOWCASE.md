# Grinta Showcase

These case studies make a narrow claim: they document what Grinta did in recorded runs and distinguish runtime completion from broader specification compliance. Exact artifacts are linked wherever they are public; unavailable or private evidence is labeled as such.

| Case study | Result | Evidence |
| --- | --- | --- |
| [4h 33m autonomous session](docs/showcase/autonomous-4h-session.md) | 16,393 events, 373 tool outcomes, one initial user turn, final state `FINISHED` | Sanitized report and committed audit summary |
| [Failure recovery](docs/showcase/compilation-failure-recovery.md) | Failure output inspected, targeted repair applied, validation rerun without a follow-up prompt | Demo recording and disclosure notes |
| [Issue-tracker build](docs/showcase/issue-tracker-build.md) | Flask + React issue tracker produced and validated with 19 passing tests | Run summary; public transcript pending sanitization |
| [Raft key-value store](docs/showcase/raft-kv-store.md) | Race-condition failure diagnosed; 39/39 tests passed consistently | Full demo and animated preview |

For the evidence standard used by the engineering narrative, see [docs/journey/EVIDENCE.md](docs/journey/EVIDENCE.md).
