$projectDir = "C:\Users\xu'zhi'cheng\Desktop\agent\search-agent\gpt-researcher"
$pythonExe = "E:\python\python.exe"
$scriptRel = "scripts\daily_hot_push.py"

# Remove old tasks
try { Unregister-ScheduledTask -TaskName 'DailyHotPushMorning' -Confirm:$false } catch {}
try { Unregister-ScheduledTask -TaskName 'DailyHotPushEvening' -Confirm:$false } catch {}

# Settings
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RunOnlyIfNetworkAvailable

# Morning: 9:00 AM
$a1 = New-ScheduledTaskAction -Execute $pythonExe -Argument $scriptRel -WorkingDirectory $projectDir
$t1 = New-ScheduledTaskTrigger -Daily -At '09:00'
Register-ScheduledTask -TaskName 'DailyHotPushMorning' -Action $a1 -Trigger $t1 -Settings $settings -Description 'Daily hot push 9am' -RunLevel Limited | Out-Null

# Evening: 8:00 PM
$a2 = New-ScheduledTaskAction -Execute $pythonExe -Argument $scriptRel -WorkingDirectory $projectDir
$t2 = New-ScheduledTaskTrigger -Daily -At '20:00'
Register-ScheduledTask -TaskName 'DailyHotPushEvening' -Action $a2 -Trigger $t2 -Settings $settings -Description 'Daily hot push 8pm' -RunLevel Limited | Out-Null

# Verify
Get-ScheduledTask -TaskName 'DailyHotPush*' | ForEach-Object {
    $info = Get-ScheduledTaskInfo $_.TaskName
    Write-Output ("{0}: State={1}, NextRun={2}" -f $_.TaskName, $_.State, $info.NextRunTime)
}
