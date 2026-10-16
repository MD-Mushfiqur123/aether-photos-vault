@echo off
title AETHER PHOTOS // INFINITE YOUTUBE OBJECT VAULT
color 0B
echo ===========================================================================
echo   AETHER PHOTOS // INFINITE YOUTUBE OBJECT VAULT
echo ===========================================================================
echo [*] Checking Python environment...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [!] Python 3.10+ was not found in PATH.
        echo [*] Please install Python from https://www.python.org/
        pause
        exit /b 1
    ) else (
        set PY_CMD=py
    )
) else (
    set PY_CMD=python
)

echo [OK] Python detected.
echo [*] Starting Aether Photos Web Server on http://localhost:8000/ ...

start "" "http://localhost:8000/"
%PY_CMD% server.py

if %errorlevel% neq 0 (
    echo.
    echo [!] Server stopped with an error.
    pause
)
