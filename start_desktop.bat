@echo off
setlocal
chcp 65001 >nul
title Research Agent

set "APP_DIR=%~dp0"
set "PACKAGED_EXE=%APP_DIR%dist\ResearchAgent\ResearchAgent.exe"

if exist "%PACKAGED_EXE%" (
    start "" "%PACKAGED_EXE%"
    exit /b 0
)

where python >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到已打包的 Research Agent，也未检测到 Python。
    echo 请运行安装程序，或按照 docs\user_manual.md 配置开发环境。
    pause
    exit /b 1
)

set "PYTHONPATH=%APP_DIR%src"

if not exist "%APP_DIR%frontend\dist\index.html" (
    echo [错误] 前端尚未构建。
    echo 请在 frontend 目录运行: node node_modules\vite\bin\vite.js build
    pause
    exit /b 1
)

python -c "import fastapi, sqlalchemy, uvicorn, webview" >nul 2>&1
if errorlevel 1 (
    echo [错误] 当前 Python 环境缺少运行依赖。
    echo 请先执行: python -m pip install -r requirements.txt
    pause
    exit /b 1
)

python -m research_agent.desktop_app
if errorlevel 1 (
    echo.
    echo [错误] Research Agent 启动失败。
    echo 日志位置: %%APPDATA%%\ResearchAgent\logs\
    pause
    exit /b 1
)

endlocal
