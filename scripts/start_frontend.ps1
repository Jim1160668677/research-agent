# 科研智能体系统 - 前端启动脚本
# 需要先安装 Node.js 18+

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " 科研智能体前端 - Research Agent UI" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$frontendDir = Join-Path $PSScriptRoot "..\frontend"

# 1. 安装依赖
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "`n[1/2] 安装前端依赖..." -ForegroundColor Yellow
    Set-Location $frontendDir
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] npm install 失败" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "`n[1/2] 依赖已安装" -ForegroundColor Green
}

# 2. 启动开发服务器
Write-Host "`n[2/2] 启动前端开发服务器 (http://localhost:5173)..." -ForegroundColor Yellow
Set-Location $frontendDir
npm run dev
