<#
    build-launcher.ps1
    Compiles scripts\toggle_launcher.cs into scripts\toggle.exe — a tiny
    windowless launcher for hotkeys (no console window / no flash).

    Uses the C# compiler that ships with the .NET Framework (always present on
    Windows), so there is nothing to install.

        powershell -ExecutionPolicy Bypass -File scripts\build-launcher.ps1
#>
$ErrorActionPreference = 'Stop'

$csc = @(
    "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $csc) {
    throw "C# compiler (csc.exe) not found under $env:WINDIR\Microsoft.NET. " +
          "Install the .NET Framework, or bind your hotkey to scripts\toggle.cmd instead."
}

$src = Join-Path $PSScriptRoot 'toggle_launcher.cs'
$out = Join-Path $PSScriptRoot 'toggle.exe'

& $csc /nologo /target:winexe /out:"$out" "$src"
if ($LASTEXITCODE -ne 0) { throw "Compilation failed (exit $LASTEXITCODE)." }

Write-Host "Built $out"
Write-Host "Bind your hotkey (e.g. in Logitech G HUB) to that .exe."
