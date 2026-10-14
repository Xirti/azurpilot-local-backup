$TaskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
# 缓存/依赖须事先准备；本脚本不运行 npm ci。
$ErrorActionPreference = 'Stop'
$node = (Get-Command node -ErrorAction Stop).Source
$npm = Join-Path (Split-Path $node) 'node_modules\npm\bin\npm-cli.js'
if (-not (Test-Path -LiteralPath (Join-Path $TaskRoot 'frontend\node_modules'))) { throw 'Prepared frontend dependencies missing.' }
Push-Location -LiteralPath $TaskRoot
try {
    & $node $npm --offline run build --prefix frontend
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $python = Join-Path $TaskRoot '.venv\Scripts\python.exe'
    & $python -X utf8 -c 'from deploy.frontend import source_fingerprint; from pathlib import Path; p=Path("frontend"); (p/"dist/.source-fingerprint").write_text(source_fingerprint(p)+"\n", encoding="utf-8")'
    exit $LASTEXITCODE
} finally { Pop-Location }
