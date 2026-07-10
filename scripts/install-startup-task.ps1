<#
    install-startup-task.ps1
    Registers a hidden scheduled task that runs mute-on-startup.ps1 at logon,
    so your speakers start muted every time you sign in.

    Run from a normal (non-admin) PowerShell:
        powershell -ExecutionPolicy Bypass -File scripts\install-startup-task.ps1

    Remove it later with uninstall-startup-task.ps1.
#>
param(
    [string]$TaskName = 'FocusriteMuteOnLogon'
)

$ErrorActionPreference = 'Stop'
$repo   = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repo 'scripts\mute-on-startup.ps1'

if (-not (Test-Path $script)) { throw "Cannot find $script" }

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"" `
    -WorkingDirectory $repo

# AtLogOn for the current user, plus a short delay so the audio stack is up.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = 'PT5S'

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName' (runs mute at logon)."
Write-Host "Test it now with:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Then check startup.log in the repo for the result."
