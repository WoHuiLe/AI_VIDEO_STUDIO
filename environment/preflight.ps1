$ErrorActionPreference = 'Stop'
foreach ($studioTool in 'py','git','ffmpeg','ffprobe') {
    $studioFound = Get-Command $studioTool -ErrorAction SilentlyContinue
    [pscustomobject]@{ Tool=$studioTool; Available=($null -ne $studioFound); Path=$studioFound.Source }
}
Get-PSDrive -PSProvider FileSystem | Select-Object Name,Used,Free
