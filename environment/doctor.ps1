$ErrorActionPreference = 'Stop'
$studioRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$studioPython = Join-Path $studioRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $studioPython)) { throw '请先运行 environment/install.ps1' }
& $studioPython -m avstudio doctor
exit $LASTEXITCODE
