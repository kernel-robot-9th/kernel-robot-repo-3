param([ValidateSet('start','stop','status')][string]$Action='start', [switch]$Auto, [int]$Port=8000)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$previewPython=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $previewPython)) { throw '프로젝트 .venv 설치가 필요합니다.' }
$previewArgs=@('scripts/preview.py',$Action,'--port',"$Port")
if ($Auto) { $previewArgs+='--auto' }
& $previewPython @previewArgs
exit $LASTEXITCODE
