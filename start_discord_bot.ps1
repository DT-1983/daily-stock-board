# Longzhongdui Discord bot (discord_bot.py) - local background start, no inbound port besides
# the local health check on 127.0.0.1:8030. Logs go to logs/discord_bot.log(.err.log).
# NOTE: keep this file ASCII-only in comments/strings. A full-width punctuation mark here
# broke PowerShell 5.1's -File parser twice (2026-09-03) because it reads .ps1 without a
# UTF-8 BOM using the system codepage (Big5) - some multi-byte sequences decode into bytes
# that look like quote/terminator characters and silently kill the whole script before it
# runs anything (no error log, no process launched - looks like "did nothing").
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path "$root\logs")) { New-Item -ItemType Directory -Path "$root\logs" | Out-Null }
Start-Process -WindowStyle Hidden "python" `
  -ArgumentList "-u", "discord_bot.py" `
  -WorkingDirectory $root `
  -RedirectStandardOutput "$root\logs\discord_bot.log" `
  -RedirectStandardError "$root\logs\discord_bot.err.log"
Write-Host "discord_bot.py started (background, logs in logs\discord_bot.log)"
