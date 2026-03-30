@echo off
REM Batch script to set up automated database backups on Windows
REM This script will run the PowerShell setup script with Administrator privileges

echo ========================================
echo App Database Backup - Windows Setup
echo ========================================
echo.

REM Check if running as Administrator
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: This script must be run as Administrator!
    echo Right-click this file and select "Run as Administrator"
    pause
    exit /b 1
)

REM Get the directory where this script is located
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..

REM Run the PowerShell script
powershell.exe -ExecutionPolicy Bypass -File "%SCRIPT_DIR%setup_windows_backup_task.ps1" -ProjectPath "%PROJECT_DIR%"

pause
