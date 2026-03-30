@echo off
REM start-with-shadcn.cmd
REM Wrapper to launch SuperGateway + shadcn-ui MCP + App.
REM Supports either positional token or -GitHubToken=TOKEN flag.
REM If .env.local exists with GITHUB_PERSONAL_ACCESS_TOKEN, no argument needed.

setlocal ENABLEDELAYEDEXPANSION
set "SCRIPT_DIR=%~dp0"
set "TOKEN="

for %%A in (%*) do (
  set "arg=%%~A"
  echo !arg! | findstr /B /I /C:"-GitHubToken=" >NUL
  if !errorlevel! EQU 0 (
    set "TOKEN=!arg:*=-GitHubToken=!"
  ) else if NOT DEFINED TOKEN (
    REM First non-flag argument treated as token
    echo !arg! | findstr /B /C:"-" >NUL
    if !errorlevel! NEQ 0 set "TOKEN=!arg!"
  )
)

if defined TOKEN (
  echo [info] Using provided GitHub token (redacted)
  powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start-with-shadcn.ps1" -GitHubToken "!TOKEN!"
) else (
  echo [info] No token argument supplied; will rely on .env.local or env vars if present.
  powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start-with-shadcn.ps1"
)

endlocal
