# 为解压后的离线包修正 Python 基础环境路径，再初始化缺失配置。
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$packageRoot = $PSScriptRoot
$basePython = Join-Path $packageRoot 'python-runtime\cpython-3.14.6-windows-x86_64-none\python.exe'
$venvPython = Join-Path $packageRoot '.venv\Scripts\python.exe'
$venvConfig = Join-Path $packageRoot '.venv\pyvenv.cfg'
$initializer = Join-Path $packageRoot 'local-maintenance\initialize_release.py'
foreach ($requiredFile in @($basePython, $venvPython, $venvConfig, $initializer)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Offline runtime file missing: $requiredFile. Download the Windows offline ZIP, not Source code.zip."
    }
}
$currentConfig = [IO.File]::ReadAllText($venvConfig)
$homePattern = '(?m)^home\s*=.*$'
if ([regex]::Matches($currentConfig, $homePattern).Count -ne 1) {
    throw 'Unexpected pyvenv.cfg format; no changes applied.'
}
$baseDirectory = Split-Path -Parent $basePython
$rewrittenConfig = [regex]::Replace($currentConfig, $homePattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($match) 'home = ' + $baseDirectory })
if ($rewrittenConfig -ne $currentConfig) {
    [IO.File]::WriteAllText($venvConfig, $rewrittenConfig, (New-Object System.Text.UTF8Encoding($false)))
}
$initializeArguments = @('-X', 'utf8', $initializer, '--root', $packageRoot)
if ($CheckOnly) { $initializeArguments += '--check' }
& $venvPython @initializeArguments
exit $LASTEXITCODE
