# Verification scripts (`backend/scripts/verify`)

Python checks used locally and in CI.

## Scripts

| File | Purpose |
| --- | --- |
| **`check_layer_imports.py`** | Enforce architectural import boundaries between backend layers |
| **`check_fastmcp_import.py`** | Verify `fastmcp` imports cleanly in the current environment |
| **`verify_api_versioning.py`** | Guardrails around public API / versioning expectations |
| **`verify_optional_imports.py`** | Smoke-import optional dependency sets |
| **`reliability_gate.py`** | Reliability gate harness (phases, optional JSON report) |

## Usage

From the repository root:

```bash
python backend/scripts/verify/check_layer_imports.py
python backend/scripts/verify/verify_api_versioning.py
python backend/scripts/verify/check_fastmcp_import.py
python backend/scripts/verify/verify_optional_imports.py
python backend/scripts/verify/reliability_gate.py --phase full
```

Include integration-oriented checks and emit a machine-readable report:

```bash
python backend/scripts/verify/reliability_gate.py --phase full --include-integration --json-report .grinta/reliability-gate-report.json
```
