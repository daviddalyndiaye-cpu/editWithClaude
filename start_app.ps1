# Starts the Auto B-Roll Studio web app on http://localhost:8765
$env:Path=[Environment]::GetEnvironmentVariable("Path","Machine")+";"+[Environment]::GetEnvironmentVariable("Path","User")
Set-Location $PSScriptRoot
.\.venv\Scripts\python.exe yta_license.py check
if ($LASTEXITCODE -ne 0) { Read-Host "Press Enter to close"; exit 1 }
.\.venv\Scripts\python.exe -m app.server
