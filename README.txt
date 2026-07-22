DMS Lector de Cédulas - Paquete Final
=====================================

Estructura de configuraciones
-----------------------------
La carpeta configs ahora se organiza así:

- configs/formularios/: configuraciones seleccionables para autocompletar formularios.
- configs/sistema/: configuración activa, favoritas y último puerto COM.
- configs/formatos/: catálogo de formatos de cédulas y documentos reconocidos.

Al iniciar el lector o el administrador, los archivos de versiones anteriores se migran automáticamente a su carpeta correspondiente sin eliminar configuraciones existentes.

Cambio rápido
-------------
Desde crear_configuracion.exe se seleccionan dos configuraciones favoritas.
Mientras el lector esté ejecutándose, Ctrl+Alt+C alterna inmediatamente entre ambas. La misma acción está disponible desde el icono de bandeja.

Control de sesiones y cierre
----------------------------
- Si ya existe otra sesión del lector, la nueva instancia permite detenerla antes de continuar.
- Las versiones nuevas solicitan el cierre de la sesión anterior de forma controlada; también existe un cierre forzado de respaldo para versiones antiguas.
- Al cambiar de usuario en la consola de Windows, la instancia anterior se cierra automáticamente.
- Las sesiones RDP se detectan para evitar cierres incorrectos durante soporte remoto.
- Cancelar la detección del lector o seleccionar Salir desde los iconos ocultos cierra el puerto COM, el atajo global, la bandeja y todos los hilos del lector.

Modo de bajo consumo
--------------------
- El proceso se ejecuta con prioridad reducida para no competir con la aplicación que contiene el formulario.
- El sondeo del puerto serial usa pausas mayores y esperas interrumpibles.
- La escritura, el pegado y las tabulaciones incorporan pequeñas pausas para evitar saturar aplicaciones lentas.
- La versión del lector con estas mejoras es la 3.9.0.

Archivos principales
--------------------
- dashboard.py: administra clientes, licencias e instaladores.
- template/main.py: inicio, selector, bandeja y coordinación de módulos.
- template/crear_configuracion.py: administrador de formularios y favoritos.
- template/lector_otras_cedulas.py: capturador auxiliar de documentos no soportados.
- template/capturar_nuevo_formato.py: herramienta RAW/HEX/Base64 para nuevos formatos.
- template/assets/runtime/dms_session_runtime.py: instancia única, cierre y supervisión de Windows.
- template/assets/runtime/dms_reader_runtime.py: lectura serial optimizada y escritura controlada.
- template/assets/runtime/dms_config_runtime.py: configuraciones, favoritas y selector.
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
- Las actualizaciones conservan la licencia y toda la carpeta configs.
- Las lecturas no reconocidas no se escriben en pantalla y se guardan para diagnóstico.
