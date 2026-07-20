@echo off
cd /d "%~dp0"
py -m pip install -r requirements.txt
py dashboard.py
pause
