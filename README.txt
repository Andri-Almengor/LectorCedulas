DMS Lector de Cédulas - Paquete Final
=====================================

Estructura de configuraciones
-----------------------------
La carpeta configs ahora se organiza así:

- configs/formularios/: configuraciones seleccionables para autocompletar formularios.
- configs/sistema/: configuración activa, favoritos y último puerto COM.
- configs/formatos/: catálogo de formatos de cédulas y documentos reconocidos.

Al iniciar el lector o el administrador, los archivos de versiones anteriores se migran automáticamente a su carpeta correspondiente sin eliminar configuraciones existentes.

Cambio rápido
-------------
Desde crear_configuracion.exe se seleccionan dos configuraciones favoritas.
Mientras el lector esté ejecutándose, Ctrl+Alt+C alterna inmediatamente entre ambas. La misma acción está disponible desde el icono de bandeja.

Archivos principales
--------------------
- dashboard.py: administra clientes, licencias e instaladores.
- template/main.py: inicio, migración, selector y atajo global.
- template/lector_otras_cedulas.py: núcleo de lectura y parsers del lector.
- template/crear_configuracion.py: administrador de formularios y favoritos.
- template/capturar_nuevo_formato.py: núcleo del editor de configuraciones usado al compilar.
- tools/capturar_nuevo_formato.py: herramienta RAW/HEX/Base64 para nuevos formatos.
- tools/lector_otras_cedulas.py: capturador auxiliar de documentos no soportados.
- template/configs/formatos/formatos_cedulas.json: catálogo actual de formatos.

Requisitos
----------
1. Python 3.10 o superior.
2. Inno Setup 6.
3. Ejecutar installer/generar_dashboard_exe.bat.
4. Abrir dist_dashboard/DashboardInstaladoresDMS.exe.
5. Crear cliente/licencia y generar el instalador.

Notas
-----
- Las actualizaciones conservan licencia y toda la carpeta configs.
- Las lecturas no reconocidas no se escriben en pantalla y se guardan para diagnóstico.
