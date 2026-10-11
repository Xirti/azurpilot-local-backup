param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$stopper = Join-Path $PSScriptRoot 'local-repairs\webui_stop.py'
if (-not (Test-Path -LiteralPath $python)) { throw "Project Python not found: $python" }
if (-not (Test-Path -LiteralPath $stopper)) { throw "Stop helper not found: $stopper" }
$stopArgs = @('-X', 'utf8', $stopper, '--root', $PSScriptRoot)
if ($CheckOnly) { $stopArgs += '--check' }
& $python @stopArgs
exit $LASTEXITCODE
