<#
.SYNOPSIS
Builds the self-contained Research Agent Windows desktop distribution.
#>

[CmdletBinding()]
param(
    [string]$OutputDir = "dist",
    [switch]$SkipFrontend,
    [switch]$InstallDependencies,
    [switch]$CreateInstaller
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$FrontendDir = Join-Path $ProjectDir "frontend"
$OutputPath = [System.IO.Path]::GetFullPath((Join-Path $ProjectDir $OutputDir))
$ProjectPath = [System.IO.Path]::GetFullPath($ProjectDir)

if (-not $OutputPath.StartsWith($ProjectPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Output directory must stay inside the project directory: $OutputPath"
}

Write-Host "Research Agent desktop build" -ForegroundColor Cyan
Write-Host "Project: $ProjectPath" -ForegroundColor DarkGray
Write-Host "Output:  $OutputPath" -ForegroundColor DarkGray

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.10 or newer is required."
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js is required to build the bundled interface."
}

Push-Location $ProjectDir
try {
    if ($InstallDependencies) {
        Write-Host "[1/4] Installing build dependencies" -ForegroundColor Yellow
        python -m pip install -r requirements.txt
        python -m pip install "pyinstaller>=6.0"
        if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
    } else {
        Write-Host "[1/4] Using the current Python environment" -ForegroundColor Yellow
        python -c "import PyInstaller, webview, fastapi, sqlalchemy"
        if ($LASTEXITCODE -ne 0) {
            throw "Build dependencies are missing. Re-run with -InstallDependencies."
        }
    }

    if (-not $SkipFrontend) {
        Write-Host "[2/4] Building the Vue interface" -ForegroundColor Yellow
        Push-Location $FrontendDir
        try {
            if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
                npm.cmd ci
                if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
            }
            node node_modules/vite/bin/vite.js build
            if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
        } finally {
            Pop-Location
        }
    }

    $IndexPath = Join-Path $FrontendDir "dist\index.html"
    if (-not (Test-Path $IndexPath)) {
        throw "Bundled interface is missing: $IndexPath"
    }

    Write-Host "[3/4] Packaging the native application" -ForegroundColor Yellow
    $WorkPath = Join-Path $ProjectDir "build\pyinstaller"
    python -m PyInstaller ResearchAgent.spec --clean --noconfirm --distpath $OutputPath --workpath $WorkPath
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

    $Executable = Join-Path $OutputPath "ResearchAgent\ResearchAgent.exe"
    if (-not (Test-Path $Executable)) {
        throw "Build finished without the expected executable: $Executable"
    }

    if ($CreateInstaller) {
        Write-Host "[4/4] Building the installer" -ForegroundColor Yellow
        $Compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if (-not $Compiler) {
            throw "Inno Setup (ISCC.exe) was not found in PATH."
        }
        & $Compiler.Source (Join-Path $ProjectDir "installer.iss")
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed." }
    } else {
        Write-Host "[4/4] Installer step skipped" -ForegroundColor Yellow
    }

    Write-Host "Build complete: $Executable" -ForegroundColor Green
} finally {
    Pop-Location
}
