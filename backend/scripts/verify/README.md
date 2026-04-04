# Verification Scripts

Scripts to verify API routes, versioning, imports, and architectural boundaries.

## Scripts

- **`verify_api_routes.py`** - Verify API route definitions and registration
- **`verify_api_versioning.py`** - Verify API versioning
- **`verify_new_endpoints_versioning.py`** - Verify new endpoint versioning
- **`check_layer_imports.py`** - Enforce layer dependency boundaries (runs in pre-commit)
- **`check_fastmcp_import.py`** - Check fastmcp import availability
- **`reliability_gate.py`** - Run Release 1 / Release 2 migration reliability gates

## Usage

```bash
# Verify API routes
python backend/scripts/verify/verify_api_routes.py

# Verify API versioning
python backend/scripts/verify/verify_api_versioning.py

# Check layer boundary imports
python backend/scripts/verify/check_layer_imports.py

# Check MCP imports
python backend/scripts/verify/check_fastmcp_import.py

# Run full reliability gate (Release 1 + Release 2 unit checks)
python backend/scripts/verify/reliability_gate.py --phase full

# Include integration filter checks and emit machine-readable report
python backend/scripts/verify/reliability_gate.py --phase full --include-integration --json-report .grinta/reliability-gate-report.json
```
