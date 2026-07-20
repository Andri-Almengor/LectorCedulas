@echo off
setlocal
cd /d "%~dp0\.."

echo ===============================================
echo  Generando DashboardInstaladoresDMS.exe
echo ===============================================

py -m pip install -r requirements.txt
if errorlevel 1 goto error
py -m pip install pyinstaller python-dateutil pillow
if errorlevel 1 goto error

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
rmdir /s /q dist_dashboard 2>nul
mkdir dist_dashboard 2>nul

echo.
echo Intentando compilar Dashboard con icono...
py -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name DashboardInstaladoresDMS ^
  --icon template\assets\DMS_icono_circulo_i.ico ^
  --add-data "template;template" ^
  --add-data "tools;tools" ^
  --add-data "requirements.txt;." ^
  dashboard.py

if errorlevel 1 (
  echo.
  echo No se pudo compilar con icono. Reintentando SIN icono por compatibilidad...
  rmdir /s /q build 2>nul
  rmdir /s /q dist 2>nul
  py -m PyInstaller --noconfirm --clean --windowed --onefile ^
    --name DashboardInstaladoresDMS ^
    --add-data "template;template" ^
    --add-data "tools;tools" ^
    --add-data "requirements.txt;." ^
    dashboard.py
  if errorlevel 1 goto error
)

copy /Y dist\DashboardInstaladoresDMS.exe dist_dashboard\DashboardInstaladoresDMS.exe >nul

echo.
echo Listo: dist_dashboard\DashboardInstaladoresDMS.exe
echo Ejecuta ese archivo para crear instaladores por cliente.
pause
exit /b 0

:error
echo.
echo ERROR: No se pudo crear el EXE del dashboard.
echo Revisa que Python, PyInstaller y permisos/antivirus esten correctos.
pause
exit /b 1
