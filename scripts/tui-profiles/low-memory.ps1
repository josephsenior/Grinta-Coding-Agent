# Grinta TUI "Low Memory" performance profile.
# Dot-source before launching the TUI:  . .\scripts\tui-profiles\low-memory.ps1

$env:GRINTA_TUI_VIEWPORT_MAX_MOUNTED = '40'
$env:GRINTA_TUI_VIEWPORT_OVERSCAN = '5'
$env:GRINTA_TUI_PENDING_EVENT_LIMIT = '1000'
$env:GRINTA_TUI_HISTORY_RENDER_LIMIT = '500'
$env:GRINTA_TUI_TERMINAL_DISPLAY_LINE_CAP = '100'

Write-Host 'Grinta TUI low-memory profile loaded.'
