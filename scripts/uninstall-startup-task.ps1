<#
    uninstall-startup-task.ps1
    Removes the logon mute scheduled task created by install-startup-task.ps1.
#>
param(
    [string]$TaskName = 'FocusriteMuteOnLogon'
)

$ErrorActionPreference = 'Stop'
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
} else {
    Write-Host "No scheduled task named '$TaskName' found."
}
