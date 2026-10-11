# Keep the existing CMD entry; wait for readiness without a fixed startup deadline.
param([switch]$NoBrowser, [switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$launcher = Join-Path $root 'local-repairs\webui_launcher.py'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python not found: $python"
}
if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Local repair launcher not found: $launcher"
}

[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$launcherArgs = @('-X', 'utf8', $launcher, '--root', $root)
if ($NoBrowser) { $launcherArgs += '--no-browser' }
if ($CheckOnly) { $launcherArgs += '--check' }
& $python @launcherArgs
exit $LASTEXITCODE
