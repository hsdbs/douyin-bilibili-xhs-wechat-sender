@echo off
cd /d "%~dp0"
rem 启动可视化管理面板（自动打开浏览器）
".venv\Scripts\python.exe" app.py
pause
