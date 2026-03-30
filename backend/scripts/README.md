# Backend Scripts

Organized collection of utility scripts for the App backend.

## Directory Structure

```
scripts/
├── database/     # Database setup, backup, and query scripts
├── setup/        # Installation and configuration scripts
├── dev/          # Development utilities and test helpers
├── verify/       # Verification and check scripts
├── build/        # Build and code generation scripts
└── mcp/          # MCP-related scripts
```

## Quick Reference

### Database Operations
```bash
python backend/scripts/database/setup_database.py
python backend/scripts/database/backup_database.py --backup
```

### Build Tasks
```bash
python backend/scripts/build/compile_protos.py
python backend/scripts/build/update_openapi.py
```

### Development
```bash
bash backend/scripts/dev/clean_pycache.sh
python backend/scripts/dev/coverage_inspect.py
```

### Verification
```bash
python backend/scripts/verify/verify_api_routes.py
python backend/scripts/verify/check_mcp_types.py
```

### Setup
```bash
python backend/scripts/setup/setup_sentry.py
.\backend\scripts\setup\start-with-shadcn.ps1
```

## See Also

- [Database Scripts](database/README.md)
- [Setup Scripts](setup/README.md)
- [Development Scripts](dev/README.md)
- [Verification Scripts](verify/README.md)
- [Build Scripts](build/README.md)
