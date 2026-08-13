# 科研智能体系统 - 启动脚本 (Windows)
# 用法:
#   1. 初始化数据库:  .\scripts\init.ps1
#   2. 启动后端:      .\scripts\start_server.ps1
#   3. 启动前端:      .\scripts\start_frontend.ps1

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " 科研智能体系统 - Research Agent" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. 检查Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "[ERROR] 未找到Python，请安装 Python 3.10+" -ForegroundColor Red
    exit 1
}

# 2. 初始化数据库
Write-Host "`n[1/3] 初始化数据库..." -ForegroundColor Yellow
$env:PYTHONPATH = Join-Path $PSScriptRoot "..\src"
python -m research_agent.init_db
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] 数据库初始化失败" -ForegroundColor Red
    exit 1
}

# 3. 安装Python依赖 (如果需要)
Write-Host "`n[2/3] 检查依赖..." -ForegroundColor Yellow
python -c "import fastapi, sqlalchemy, aiosqlite, loguru, scipy, matplotlib, networkx" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "正在安装依赖，请稍候..." -ForegroundColor Yellow
    pip install fastapi uvicorn sqlalchemy aiosqlite pydantic pydantic-settings loguru httpx scipy numpy matplotlib networkx cryptography
}

# 4. 启动后端服务
Write-Host "`n[3/3] 启动后端服务 (http://localhost:8010)..." -ForegroundColor Yellow
Write-Host "API文档: http://localhost:8010/docs" -ForegroundColor Green
Write-Host "按 Ctrl+C 停止服务`n" -ForegroundColor Gray

python -m research_agent.main
