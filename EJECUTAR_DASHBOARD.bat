@echo off
setlocal
cd /d "%~dp0"
py -m pip install -r requirements.lock
py dashboard.py
pause
