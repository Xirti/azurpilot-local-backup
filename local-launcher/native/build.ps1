param([Parameter(Mandatory=$true)][string]$EmbeddedVideoPath)
$ErrorActionPreference = 'Stop'
$TaskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$TaskCompiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $TaskCompiler)) { throw '缺少 .NET Framework C# 编译器。' }
if (-not (Test-Path -LiteralPath $EmbeddedVideoPath -PathType Leaf)) { throw "Embedded video missing." }
& $TaskCompiler /nologo /target:winexe /platform:x64 /optimize+ /utf8output "/win32manifest:$PSScriptRoot\app.manifest" "/out:$TaskRoot\AzurPilot-Local.exe" "/win32icon:$TaskRoot\local-launcher\ui\assets\icon.ico" /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll "/reference:$PSScriptRoot\Microsoft.Web.WebView2.Core.dll" "/reference:$PSScriptRoot\Microsoft.Web.WebView2.WinForms.dll" "/resource:$TaskRoot\local-launcher\ui\assets\MiSansLauncher.woff2,AzurPilot.Fonts.MiSansLauncher.woff2" "/resource:$TaskRoot\local-launcher\ui\assets\CormorantGaramond.ttf,AzurPilot.Fonts.CormorantGaramond.ttf" "/resource:$TaskRoot\local-launcher\ui\assets\LauncherSerif.woff2,AzurPilot.Fonts.LauncherSerif.woff2" "$PSScriptRoot\Launcher.cs" "$PSScriptRoot\DesktopForm.cs" "$PSScriptRoot\EmbeddedMedia.cs" "$PSScriptRoot\ManagedEntry.cs" "$PSScriptRoot\LauncherDiagnostics.cs" "/resource:$EmbeddedVideoPath,AzurPilot.Media.Background.mp4"
if ($LASTEXITCODE -ne 0) { throw '启动器编译失败。' }
