# Verification Scripts

Scripts to verify API routes, versioning, imports, and architectural boundaries.

## Scripts

- **`verify_api_routes.py`** - Verify API route definitions and registration
- **`verify_api_versioning.py`** - Verify API versioning
- **`verify_new_endpoints_versioning.py`** - Verify new endpoint versioning
- **`check_layer_imports.py`** - Enforce layer dependency boundaries (runs in pre-commit)
- **`check_fastmcp_import.py`** - Check fastmcp import availability

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
```
