$ErrorActionPreference = 'Stop'
$studioRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$studioPython = Join-Path $studioRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $studioPython)) { throw '请先运行 environment/install.ps1 -Dev' }
Push-Location $studioRoot
try {
    & $studioPython -m avstudio doctor --output (Join-Path $studioRoot 'docs\reports\environment.json')
    if ($LASTEXITCODE -ne 0) { throw '环境检查未通过' }
    & $studioPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw '依赖一致性检查未通过' }
    & $studioPython -m pytest -q '--junitxml=docs/reports/tests.xml'
    if ($LASTEXITCODE -ne 0) { throw '自动化测试未通过' }
} finally { Pop-Location }
