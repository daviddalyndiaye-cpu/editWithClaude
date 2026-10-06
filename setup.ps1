# One-time setup for Auto B-Roll Studio on Windows 10/11.
# Run in PowerShell from the repo folder:   powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
function Has($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function RefreshPath { $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User") }

Write-Host "== 1/5 System tools (Python 3.12, FFmpeg, Node.js)" -ForegroundColor Cyan
if (-not (Test-Path "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")) {
  winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements }
if (-not (Has ffmpeg)) { winget install --id Gyan.FFmpeg -e --source winget --accept-package-agreements --accept-source-agreements }
if (-not (Has node))   { winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements }
RefreshPath

Write-Host "== 2/5 Python environment (.venv) - whisperx/PyTorch is a large download" -ForegroundColor Cyan
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
if (-not (Test-Path .venv)) { & $py -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "== 3/5 HyperFrames renderer (npm) + headless Chrome" -ForegroundColor Cyan
npm install
npx hyperframes browser ensure

Write-Host "== 4/5 Config" -ForegroundColor Cyan
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env - open it and paste your GEMINI_API_KEY" -ForegroundColor Yellow }
if (-not (Test-Path cookies.txt)) { Write-Host "Missing cookies.txt - see README step 'YouTube cookies'" -ForegroundColor Yellow }

Write-Host "== 5/5 Check" -ForegroundColor Cyan
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m studio.preflight
Write-Host "Done. Start the app with:  powershell -ExecutionPolicy Bypass -File start_app.ps1   then open http://localhost:8765" -ForegroundColor Green
