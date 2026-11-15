param([switch]$Execute)
$ErrorActionPreference = 'Stop'
$studioRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$studioVenv = [System.IO.Path]::GetFullPath((Join-Path $studioRoot '.venv'))
if (-not $studioVenv.StartsWith($studioRoot + [System.IO.Path]::DirectorySeparatorChar)) { throw '目标不在工程内' }
if (-not (Test-Path -LiteralPath $studioVenv)) { Write-Output '本工程虚拟环境不存在'; exit 0 }
$studioItem = Get-Item -LiteralPath $studioVenv -Force
if ($studioItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { throw '拒绝删除链接指向的环境' }
if (-not (Test-Path -LiteralPath (Join-Path $studioVenv 'pyvenv.cfg'))) { throw '目标不是可识别的 Python 虚拟环境' }
if (-not $Execute) { Write-Output "预览：仅删除 $studioVenv；正式执行需 -Execute。项目素材及系统软件保留。"; exit 0 }
Remove-Item -LiteralPath $studioVenv -Recurse -Force
