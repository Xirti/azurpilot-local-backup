# 只使用本机缓存；缺少缓存时明确失败，不会联网补下载。
$ErrorActionPreference = 'Stop'
$env:UV_PYTHON_DOWNLOADS = 'never'
$env:UV_LINK_MODE = 'copy'
$uv = Join-Path $PSScriptRoot 'python-runtime\tools\uv.exe'
if (-not (Test-Path -LiteralPath $uv)) {
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -eq $command) { throw 'Local uv missing; prepare Python and uv before offline installation.' }
    $uv = $command.Source
}
if ([IO.Path]::GetFullPath($uv).StartsWith((Join-Path $PSScriptRoot '.venv') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'uv must be outside the virtual environment being rebuilt on Windows.'
}
$python = Join-Path $PSScriptRoot 'python-runtime\cpython-3.14.6-windows-x86_64-none\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Prepared CPython 3.14.6 missing; see OFFLINE_BUILD.md.' }
& $uv sync --frozen --offline --no-dev --python $python --project $PSScriptRoot
exit $LASTEXITCODE
