param(
  [string]$TargetDir = "dist\python",
  [string]$PythonExe = "python"
)

if (-not (Test-Path $TargetDir)) { New-Item -ItemType Directory -Path $TargetDir | Out-Null }

& $PythonExe -m venv (Join-Path $TargetDir 'python')
$venvPython = Join-Path $TargetDir 'python\Scripts\python.exe'
& $venvPython -m pip install --upgrade pip
if (Test-Path 'civic_contact_finder\requirements.txt') {
  & $venvPython -m pip install -r 'civic_contact_finder\requirements.txt'
}
Write-Host "Bundled python venv at $TargetDir\python"