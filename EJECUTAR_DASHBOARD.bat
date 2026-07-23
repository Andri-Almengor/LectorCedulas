@echo off
setlocal
cd /d "%~dp0"

py -m pip install -r requirements-build.txt
if errorlevel 1 (
    echo.
    echo No se pudieron instalar las dependencias necesarias para generar instaladores.
    echo Revisa la conexion a Internet y vuelve a ejecutar este archivo.
    pause
    exit /b 1
)

py dashboard.py
pause
