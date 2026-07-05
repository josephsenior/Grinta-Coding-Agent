# Grinta TUI "Fast Streaming" performance profile.
# Dot-source before launching the TUI:  . .\scripts\tui-profiles\fast-streaming.ps1

$env:GRINTA_TUI_VIEWPORT_MAX_MOUNTED = '50'
$env:GRINTA_TUI_STREAM_PAINT_INTERVAL = '0.033'
$env:GRINTA_TUI_PENDING_EVENT_LIMIT = '2000'
$env:GRINTA_TUI_HISTORY_RENDER_LIMIT = '800'
$env:GRINTA_TUI_TERMINAL_DISPLAY_LINE_CAP = '200'

Write-Host 'Grinta TUI fast-streaming profile loaded.'
