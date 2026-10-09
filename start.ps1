<#
  MediAgent 一键启动（Windows / PowerShell）
  · 首次运行会自动创建虚拟环境并安装依赖
  · 随后同时拉起 FastAPI 后端与 Vite 前端，并打开浏览器
#>
param(
  [switch]$SkipInstall,
  [switch]$BackendOnly,
  [switch]$Build
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root

function Find-Python {
  $candidates = @()
  foreach ($name in @("python", "python3")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
  }
  $candidates += @(
    "D:\Anaconda3\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "C:\Python312\python.exe",
    "C:\Python311\python.exe"
  )
  foreach ($exe in $candidates) {
    if (-not (Test-Path $exe)) { continue }
    $version = & $exe -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
    if ($version -and [version]$version -ge [version]"3.11") { return $exe }
  }
  throw "需要 Python 3.11 及以上版本（LangGraph 的异步 interrupt() 依赖 3.11+）。当前未找到合适的解释器。"
}

$python = Find-Python
Write-Host "使用 Python: $python" -ForegroundColor Cyan

$venv = Join-Path $Root ".venv"
if (-not (Test-Path "$venv\Scripts\python.exe")) {
  Write-Host "创建虚拟环境 .venv ..." -ForegroundColor Cyan
  & $python -m venv $venv
}

$venvPython = "$venv\Scripts\python.exe"

if (-not $SkipInstall) {
  Write-Host "安装后端依赖 ..." -ForegroundColor Cyan
  & $venvPython -m pip install --upgrade pip --quiet
  & $venvPython -m pip install -r requirements.txt --quiet
}

if (-not $BackendOnly -and -not (Test-Path "$Root\frontend\node_modules")) {
  Write-Host "安装前端依赖（首次较慢）..." -ForegroundColor Cyan
  Push-Location "$Root\frontend"
  npm install --no-audit --no-fund
  Pop-Location
}

if ($Build) {
  Write-Host "构建前端静态资源 ..." -ForegroundColor Cyan
  Push-Location "$Root\frontend"
  npm run build
  Pop-Location
  Write-Host "构建完成：http://127.0.0.1:8000 （后端直接托管 frontend/dist）" -ForegroundColor Green
  & $venvPython -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
  exit 0
}

Write-Host "启动后端 FastAPI (8000) ..." -ForegroundColor Green
$backend = Start-Process -FilePath $venvPython `
  -ArgumentList "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000" `
  -WorkingDirectory $Root -PassThru

if ($BackendOnly) {
  Write-Host "后端已启动：http://127.0.0.1:8000/docs" -ForegroundColor Green
  Write-Host "按 Ctrl+C 结束本提示后，可用 stop.ps1 关闭后端进程。" -ForegroundColor DarkGray
  exit 0
}

Write-Host "启动前端 Vite (5173) ..." -ForegroundColor Green
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm run dev" -WorkingDirectory "$Root\frontend"
Start-Sleep -Seconds 3
Start-Process "http://127.0.0.1:5173"

Write-Host ""
Write-Host "MediAgent 已启动：" -ForegroundColor Green
Write-Host "  前端：http://127.0.0.1:5173  （登录身份：医生 / 质控 / 患者 / 管理员）" -ForegroundColor White
Write-Host "  后端：http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host "  关闭：运行 .\stop.ps1" -ForegroundColor DarkGray
