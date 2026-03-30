# PowerShell script to set up automated database backups on Windows
# Run this script as Administrator to create a scheduled task

param(
    [string]$BackupTime = "02:00",  # Default: 2:00 AM
    [string]$ProjectPath = $PSScriptRoot,
    [string]$PythonPath = "python"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "App Database Backup - Windows Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator!" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Yellow
    exit 1
}

# Get absolute paths
$ProjectPath = Resolve-Path $ProjectPath
$BackupScript = Join-Path $ProjectPath "scripts\backup_database.py"
$LogFile = Join-Path $ProjectPath "logs\backup.log"

# Verify backup script exists
if (-not (Test-Path $BackupScript)) {
    Write-Host "ERROR: Backup script not found at: $BackupScript" -ForegroundColor Red
    exit 1
}

# Create logs directory if it doesn't exist
$LogDir = Split-Path $LogFile -Parent
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    Write-Host "Created logs directory: $LogDir" -ForegroundColor Green
}

# Task name
$TaskName = "App-Database-Backup"

# Check if task already exists
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Task '$TaskName' already exists." -ForegroundColor Yellow
    $response = Read-Host "Do you want to update it? (y/n)"
    if ($response -ne "y") {
        Write-Host "Cancelled." -ForegroundColor Yellow
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task." -ForegroundColor Green
}

# Create the action (command to run)
$Action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$BackupScript`" --backup" `
    -WorkingDirectory $ProjectPath

# Create the trigger (daily at specified time)
$Trigger = New-ScheduledTaskTrigger -Daily -At $BackupTime

# Create settings
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false `
    -WakeToRun:$false `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# Create the principal (run as current user)
$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest

# Register the task
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "Automated daily backup of App PostgreSQL database" | Out-Null

    Write-Host ""
    Write-Host "✓ Scheduled task created successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Task Details:" -ForegroundColor Cyan
    Write-Host "  Name: $TaskName" -ForegroundColor White
    Write-Host "  Schedule: Daily at $BackupTime" -ForegroundColor White
    Write-Host "  Script: $BackupScript" -ForegroundColor White
    Write-Host "  Log: $LogFile" -ForegroundColor White
    Write-Host ""
    Write-Host "To view the task:" -ForegroundColor Yellow
    Write-Host "  Task Scheduler → Task Scheduler Library → $TaskName" -ForegroundColor White
    Write-Host ""
    Write-Host "To test the task manually:" -ForegroundColor Yellow
    Write-Host "  Right-click the task → Run" -ForegroundColor White
    Write-Host ""
    Write-Host "To modify the schedule:" -ForegroundColor Yellow
    Write-Host "  Right-click the task → Properties → Triggers" -ForegroundColor White
    Write-Host ""

} catch {
    Write-Host "ERROR: Failed to create scheduled task: $_" -ForegroundColor Red
    exit 1
}

# Test the backup script
Write-Host "Testing backup script..." -ForegroundColor Cyan
try {
    & $PythonPath $BackupScript --backup
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Backup test successful!" -ForegroundColor Green
    } else {
        Write-Host "⚠ Backup test completed with warnings" -ForegroundColor Yellow
    }
} catch {
    Write-Host "⚠ Backup test failed: $_" -ForegroundColor Yellow
    Write-Host "  Make sure your database is running and credentials are set in .env" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup complete!" -ForegroundColor Green
