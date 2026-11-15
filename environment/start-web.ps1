param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$studioRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$studioPython = Join-Path $studioRoot '.venv\Scripts\python.exe'
$studioUrl = 'http://127.0.0.1:8765'
if (-not (Test-Path -LiteralPath $studioPython)) { throw '请先运行 environment/install.ps1' }
$studioRunning = $false
try {
    $studioConfig = Invoke-RestMethod -Uri ($studioUrl + '/api/config') -TimeoutSec 2
    $studioRunning = $studioConfig.service -eq 'avstudio-desk' -and $studioConfig.workspace -eq $studioRoot
} catch { }
if (-not $studioRunning) {
    if (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) { throw '8765 端口被其他程序占用，请人工检查；不会终止已有程序。' }
    $studioLogs = Join-Path $studioRoot 'logs'
    New-Item -ItemType Directory -Path $studioLogs -Force | Out-Null
    $studioArgs = @('-m', 'avstudio', 'web', '--workspace', ('"' + $studioRoot + '"'), '--port', '8765')
    $studioProcess = Start-Process -FilePath $studioPython -ArgumentList $studioArgs -WorkingDirectory $studioRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $studioLogs 'web.stdout.log') -RedirectStandardError (Join-Path $studioLogs 'web.stderr.log') -PassThru
    Set-Content -LiteralPath (Join-Path $studioLogs 'web.pid') -Value $studioProcess.Id
    for ($studioAttempt = 0; $studioAttempt -lt 20; $studioAttempt++) {
        Start-Sleep -Milliseconds 250
        try { $studioConfig = Invoke-RestMethod -Uri ($studioUrl + '/api/config') -TimeoutSec 1; if ($studioConfig.service -eq 'avstudio-desk') { $studioRunning = $true; break } } catch { }
        if ($studioProcess.HasExited) { break }
    }
    if (-not $studioRunning) { throw '本地网页启动失败，请查看 logs/web.stderr.log' }
}
Write-Output "制作台已启动：$studioUrl"
if (-not $NoBrowser) { Start-Process $studioUrl }
