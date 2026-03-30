# Setup Scripts

Scripts for installation, configuration, and environment setup.

## Scripts

- **`setup_sentry.py`** - Configure Sentry error tracking
- **`setup_windows_backup_task.bat`** - Setup Windows backup task (batch)
- **`setup_windows_backup_task.ps1`** - Setup Windows backup task (PowerShell)
- **`find_postgresql.ps1`** - Find PostgreSQL installation on Windows
- **`set_app_api_key.ps1`** - Set app API key in environment
- **`start-with-shadcn.cmd`** - Start App with shadcn-ui MCP proxy (CMD)
- **`start-with-shadcn.ps1`** - Start App with shadcn-ui MCP proxy (PowerShell)

## Usage

```bash
# Setup Sentry
python backend/scripts/setup/setup_sentry.py

# Setup Windows backup task
.\backend\scripts\setup\setup_windows_backup_task.ps1

# Start with shadcn-ui
.\backend\scripts\setup\start-with-shadcn.ps1
```
