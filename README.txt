DMS Lector de Cédulas - Paquete Final Corregido
===============================================

Contenido principal:
- dashboard.py: dashboard para administrar clientes/licencias y generar instaladores Setup.exe.
- template/: archivos base del lector que se empacan dentro del instalador.
- template/main.py: lector actualizado con cédula XOR, menores/CSV, QR TSE online, CI corto y mdoc ISO18013.
- template/configs/formatos_cedulas.json: formatos actuales.
- template/assets/DMS_icono_circulo_i.ico: logo usado en EXE, ventanas, accesos directos e instalador cuando Windows/Inno lo permite.
- installer/generar_dashboard_exe.bat: crea dist_dashboard/DashboardInstaladoresDMS.exe.
- EJECUTAR_DASHBOARD.bat: abre el dashboard usando Python, útil si aún no has generado el EXE.

Correcciones incluidas:
- Corregido el error de Tkinter: NameError con la variable e en callbacks de errores.
- El dashboard ya no se cae cuando Inno Setup falla aplicando el icono al Setup.exe.
- Si Inno muestra EndUpdateResource failed (110), reintenta automáticamente sin SetupIconFile.
- La app instalada y los accesos directos siguen usando el logo DMS aunque el Setup.exe no pueda recibir icono.
- El generador del EXE del dashboard también reintenta sin icono si PyInstaller falla por el recurso .ico.

Requisitos para crear instaladores:
1. Python 3.10+ instalado.
2. Inno Setup 6 instalado.
3. Ejecutar installer/generar_dashboard_exe.bat para crear el EXE del dashboard.
4. Abrir dist_dashboard/DashboardInstaladoresDMS.exe.
5. Crear cliente/licencia y presionar Generar instalador.

Notas:
- Si Windows Defender/antivirus bloquea el Setup.exe, agrega la carpeta del paquete a exclusiones o genera en una carpeta simple como C:\DMS_Builds.
- El lector conserva último COM, bandeja de Windows, cambio de configuración y validaciones anti-basura.
- El formato mdoc ISO18013 se reconoce y no escribe basura; si no hay datos visibles, usa DESCONOCIDO.
