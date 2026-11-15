$ErrorActionPreference = 'Stop'
$studioRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$studioPidFile = Join-Path $studioRoot 'logs\web.pid'
if (-not (Test-Path -LiteralPath $studioPidFile)) { Write-Output 'Local web service is not running.'; return }
$studioPidText = (Get-Content -LiteralPath $studioPidFile -Raw).Trim()
if ($studioPidText -notmatch '^\d+$') { throw 'Invalid service PID file.' }
$studioProcess = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $studioPidText) -ErrorAction SilentlyContinue
if ($studioProcess) {
    if ($studioProcess.CommandLine -notmatch '-m\s+avstudio\s+web' -or $studioProcess.CommandLine -notmatch [regex]::Escape($studioRoot)) { throw 'PID belongs to another process; refusing to stop it.' }
    Stop-Process -Id ([int]$studioPidText)
}
Remove-Item -LiteralPath $studioPidFile
Write-Output 'Local web service stopped. Project files retained.'
