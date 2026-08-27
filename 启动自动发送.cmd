@echo off
cd /d "%~dp0"

set "PY_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist "E:\py\python.exe" (
    set "PY_EXE=E:\py\python.exe"
)

"%PY_EXE%" app.py
if errorlevel 1 pause
