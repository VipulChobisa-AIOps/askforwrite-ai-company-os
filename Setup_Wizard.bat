@echo off
setlocal enabledelayedexpansion
title AskforWrite AI Company OS - Production Setup Wizard
color 0B

echo =======================================================================
echo         ASKFORWRITE AI COMPANY OS - DESKTOP SETUP WIZARD
echo =======================================================================
echo.
echo Welcome to the AskforWrite AI Company OS Setup Wizard!
echo This wizard will configure your environment, initialize the trust
echo ledger database, create Desktop shortcuts, and launch the Control Center.
echo.
echo =======================================================================
echo [1/4] Checking System Environment...
echo.

cd /d "%~dp0"

rem Check for Python or Bundled Executable
if exist "dist\AskforWrite_Company_OS\AskforWrite_Company_OS.exe" (
    echo [OK] Standalone Executable found at:
    echo      dist\AskforWrite_Company_OS\AskforWrite_Company_OS.exe
    set APP_EXE="%~dp0dist\AskforWrite_Company_OS\AskforWrite_Company_OS.exe"
) else (
    echo [INFO] Standalone executable not built yet. Using Virtual Environment Python...
    if exist ".venv\Scripts\python.exe" (
        set PYTHON_EXE="%~dp0.venv\Scripts\python.exe"
        echo [OK] Virtual Environment Python detected.
    ) else (
        set PYTHON_EXE=python
        echo [INFO] Using system Python.
    )
)

echo.
echo =======================================================================
echo [2/4] Verifying Configuration and Secrets (.env)...
echo.

if not exist ".env" (
    if exist ".env.example" (
        echo Creating default .env from .env.example...
        copy ".env.example" ".env" >nul
        echo [OK] .env created.
    ) else (
        echo [WARN] .env.example not found. Creating standard .env...
        (
            echo APP_ENV=development
            echo DATABASE_URL=sqlite:///./company_os.db
            echo APP_PORT=8000
        ) > ".env"
    )
) else (
    echo [OK] .env configuration file present.
)

echo.
echo =======================================================================
echo [3/4] Initializing Database Schema and Genesis Trust Ledger...
echo.

if defined PYTHON_EXE (
    %PYTHON_EXE% -c "from app.db.database import Base, engine, SessionLocal; from app.db.models import TrustBlock; from app.security.trust_chain import ensure_genesis_block; Base.metadata.create_all(bind=engine); s = SessionLocal(); ensure_genesis_block(s); s.commit(); print(f'  [OK] Genesis trust block confirmed. Total blocks: {s.query(TrustBlock).count()}'); s.close()"
) else (
    echo Database will be initialized automatically when the application starts.
)

echo.
echo =======================================================================
echo [4/4] Creating Windows Desktop Shortcut...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $d = [System.Environment]::GetFolderPath('Desktop'); $s = $ws.CreateShortcut(\"$d\AskforWrite AI Company OS.lnk\"); if (Test-Path 'dist\AskforWrite_Company_OS\AskforWrite_Company_OS.exe') { $s.TargetPath = (Resolve-Path 'dist\AskforWrite_Company_OS\AskforWrite_Company_OS.exe').Path } else { $s.TargetPath = (Resolve-Path '.venv\Scripts\python.exe').Path; $s.Arguments = 'desktop_app.py' }; $s.WorkingDirectory = (Resolve-Path '.').Path; $s.Description = 'AskforWrite AI Company OS - Control Center'; $s.Save(); Write-Host '  [OK] Shortcut created on Desktop: AskforWrite AI Company OS.lnk'"

echo.
echo =======================================================================
echo                      SETUP COMPLETED SUCCESSFULLY!
echo =======================================================================
echo.
echo You can now run the application from your Desktop shortcut or directly below.
echo.
set /p LAUNCH="Would you like to launch the Desktop Control Center now? (Y/n): "
if /i "%LAUNCH%"=="n" (
    echo.
    echo Setup finished. Press any key to exit.
    pause >nul
    exit /b 0
)

echo.
echo Starting AskforWrite AI Company OS...
if exist "dist\AskforWrite_Company_OS\AskforWrite_Company_OS.exe" (
    start "" "dist\AskforWrite_Company_OS\AskforWrite_Company_OS.exe"
) else (
    start "" %PYTHON_EXE% desktop_app.py
)

exit /b 0
