param(
    [ValidateSet('preview','install','status','start','remove')][string]$Action = 'preview',
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$researchRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$researchTask = 'MichuplPreMetar-EntryTiming-v1'
$researchDescription = 'michupl-pre-metar EXP0017 read-only entry timing observer; separate research journal'
$researchExe = Join-Path $researchRoot '.venv\Scripts\pythonw.exe'
$researchArguments = '-m premetar.research.entry_timing_monitor watch'
$researchUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$researchConfiguration = [ordered]@{
    TaskName=$researchTask; Execute=$researchExe; Arguments=$researchArguments
    WorkingDirectory=$researchRoot; Trigger='Current user logon'; User=$researchUser
    RunLevel='Limited'; MultipleInstances='IgnoreNew'; Restart='60 seconds x 3'
    Description=$researchDescription; BeforeLogin=$false; PasswordStored=$false
}
if ($Action -eq 'preview' -or ($Action -in @('install','remove') -and -not $Apply)) {
    $researchConfiguration | ConvertTo-Json
    return
}
$researchExisting = Get-ScheduledTask -TaskName $researchTask -ErrorAction SilentlyContinue
if ($researchExisting) {
    $researchActions = @($researchExisting.Actions)
    if ($researchExisting.Description -ne $researchDescription -or $researchActions.Count -ne 1 -or
        $researchActions[0].Execute -ne $researchExe -or
        $researchActions[0].Arguments -ne $researchArguments -or
        $researchActions[0].WorkingDirectory -ne $researchRoot) {
        throw 'Task ownership mismatch; refusing mutation'
    }
}
switch ($Action) {
    'status' {
        [ordered]@{ Exists=[bool]$researchExisting; State=if($researchExisting){$researchExisting.State.ToString()}else{'ABSENT'}; Configuration=$researchConfiguration } | ConvertTo-Json -Depth 4
    }
    'install' {
        if (-not (Test-Path -LiteralPath $researchExe -PathType Leaf)) { throw 'Project interpreter missing' }
        if ($researchExisting) { throw 'Owned task already exists; inspect status instead of replacing it' }
        $researchLaunch = New-ScheduledTaskAction -Execute $researchExe -Argument $researchArguments -WorkingDirectory $researchRoot
        $researchTrigger = New-ScheduledTaskTrigger -AtLogOn -User $researchUser
        $researchPrincipal = New-ScheduledTaskPrincipal -UserId $researchUser -LogonType Interactive -RunLevel Limited
        $researchSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $researchTask -Action $researchLaunch -Trigger $researchTrigger -Principal $researchPrincipal -Settings $researchSettings -Description $researchDescription | Select-Object TaskName,State
    }
    'start' {
        if (-not $researchExisting) { throw 'Task not installed' }
        Start-ScheduledTask -TaskName $researchTask
    }
    'remove' {
        if ($researchExisting -and $researchExisting.State.ToString() -eq 'Running') { throw 'Observer running; request graceful shutdown before removing task' }
        if ($researchExisting) { Unregister-ScheduledTask -TaskName $researchTask -Confirm:$false }
    }
}
