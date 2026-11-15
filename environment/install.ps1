param([switch]$Dev)
$ErrorActionPreference = 'Stop'
$studioRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$studioPython = Join-Path $studioRoot '.venv\Scripts\python.exe'
$studioVenv = Join-Path $studioRoot '.venv'
if (Test-Path -LiteralPath $studioVenv) {
    $studioItem = Get-Item -LiteralPath $studioVenv -Force
    if ($studioItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { throw '拒绝修改链接指向的环境' }
    if (-not (Test-Path -LiteralPath (Join-Path $studioVenv 'pyvenv.cfg'))) { throw '.venv 已存在但不是有效虚拟环境，请人工检查' }
}
if (-not (Test-Path -LiteralPath $studioPython)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw '需要已安装的 Python 3.11+；不会自动安装系统软件。' }
    & py -3.11 -m venv (Join-Path $studioRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw '创建独立虚拟环境失败' }
}
$studioPrefix = & $studioPython -c 'import sys; print(sys.prefix)'
if ($LASTEXITCODE -ne 0 -or [System.IO.Path]::GetFullPath($studioPrefix) -ne [System.IO.Path]::GetFullPath($studioVenv)) { throw '解释器不属于本工程虚拟环境' }
$lockFile = Join-Path $studioRoot 'environment\requirements.lock.txt'
& $studioPython -m pip install -r $lockFile
if ($LASTEXITCODE -ne 0) { throw '安装锁定依赖失败' }
$installTarget = if ($Dev) { $studioRoot + '[dev]' } else { $studioRoot }
& $studioPython -m pip install --no-build-isolation --no-deps -e $installTarget
if ($LASTEXITCODE -ne 0) { throw '安装工程失败' }
& $studioPython -m avstudio doctor --output (Join-Path $studioRoot '.venv\install-report.json')
if ($LASTEXITCODE -ne 0) { throw '环境检查失败' }
