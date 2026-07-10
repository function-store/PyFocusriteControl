<#
    mute-on-startup.ps1
    Mutes the Focusrite speaker/monitor output at logon.

    At logon the Focusrite Control Server (and the device) may not be ready yet,
    so this retries for a while until discovery succeeds. Registered as a hidden
    scheduled task by install-startup-task.ps1.
#>
param(
    [int]$MaxAttempts = 15,
    [int]$DelaySeconds = 4
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot          # ...\MyFocusriteControl
$fc   = Join-Path $repo 'fc.py'
$log  = Join-Path $repo 'startup.log'

"[{0}] startup mute beginning" -f (Get-Date -Format s) | Out-File $log -Append -Encoding utf8

for ($i = 1; $i -le $MaxAttempts; $i++) {
    try {
        $out = & py -3 $fc mute 2>&1
        $rc = $LASTEXITCODE
    } catch {
        $out = $_.Exception.Message
        $rc = 1
    }
    "[{0}] attempt {1}/{2} rc={3} {4}" -f (Get-Date -Format s), $i, $MaxAttempts, $rc, ($out -join ' ') |
        Out-File $log -Append -Encoding utf8
    if ($rc -eq 0) { exit 0 }
    Start-Sleep -Seconds $DelaySeconds
}

"[{0}] gave up after {1} attempts" -f (Get-Date -Format s), $MaxAttempts | Out-File $log -Append -Encoding utf8
exit 1
