@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m steempeg
if errorlevel 1 pause
