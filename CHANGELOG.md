# Changelog

## 4.0.0-qa8 — 2026-07-23

### Ciclo único de lectura

- Desde que una lectura entra al parser, el runtime reserva un único ciclo de trabajo.
- Cualquier cédula pasada mientras otra se procesa o escribe se descarta y nunca queda pendiente.
- Al finalizar una escritura, cancelación o fallo de entrega comienza un enfriamiento exacto de 2 segundos.
- Las lecturas realizadas durante el enfriamiento también se descartan; debe volver a pasarse la cédula cuando termine.
- La cola efectiva queda limitada a un solo trabajo y ya no reproduce ráfagas antiguas después de terminar la lectura actual.
- Una lectura rechazada por formato, configuración o validación libera el ciclo inmediatamente y no aplica enfriamiento.
- Si un trabajo pendiente se elimina antes de escribir, la reserva se libera sin reproducirlo posteriormente.

## 4.0.0-qa7 — 2026-07-23

### Integridad de cada lectura

- La trama serial necesita una segunda ventana de silencio estable antes de cerrarse.
- Los fragmentos tardíos recibidos durante la estabilización se anexan a la misma lectura.
- La ventana objetivo se captura al llegar el primer bloque de la cédula, no al finalizar el frame.
- El parsing se procesa en orden estricto para impedir que una consulta TSE adelante otra lectura.
- Una compuerta semántica rechaza identificaciones truncadas, fechas imposibles y nombres incompletos antes de tocar el formulario.
- La configuración activa define qué campos deben existir: el modo rápido permite solo cédula, mientras el modo completo exige sus datos configurados.

### Escritura y cambios de configuración

- Cambiar configuración ya no cancela una escritura iniciada; la transacción actual termina completa.
- Los trabajos pendientes de la configuración anterior sí se descartan mediante una barrera de generación.
- Una lectura conserva la generación activa al entrar al pipeline; si el modo cambia antes del enqueue, se rechaza y solicita reescanear.
- `Ctrl+Alt+Esc` conserva la cancelación inmediata como acción de emergencia explícita.
- El respaldo Unicode verifica la ventana exacta antes de cada carácter y después de cada campo.
- El pegado por portapapeles valida nuevamente el objetivo antes y después de `Ctrl+V`.
- Los fallos registran cuántos campos o caracteres llegaron a enviarse para facilitar el diagnóstico.

### Concurrencia, cierre y actualización

- La selección de configuración y la creación del trabajo forman una transición atómica.
- El COM se confirma como válido solamente después de que la lectura entra realmente en la cola.
- El cierre del gestor serial y de la cola espera a sus hilos para evitar instancias superpuestas.
- El actualizador espera la desaparición real de los mutex del worker y del supervisor antes de reemplazar archivos.
- Los updates preservan `licencia.key`, formularios, COM, favoritas y estado local; únicamente `configs/formatos` es administrado por DMS.
- El ZIP de actualización incluye el catálogo oficial firmado para corregir formatos en instalaciones existentes.
- Una reinstalación reemplaza el catálogo oficial, pero no sobrescribe formularios ni estado del cliente.
- GitHub Actions agrega reportes JUnit y un build smoke de PyInstaller en Windows.

### Licencias, dashboard y builds

- La emisión rechaza IDs vacíos, fechas sin zona horaria y expiraciones no posteriores a la emisión antes de firmar.
- Los pares Ed25519 se crean con escritura atómica y la clave pública puede reconstruirse desde la privada existente sin cambiar la identidad de firma.
- El build real declara explícitamente supervisor, portapapeles seguro y compuerta de calidad para PyInstaller.
- La copia de la plantilla excluye `build`, `dist`, logs, diagnósticos, specs y cachés.
- El cuadro de generación del dashboard bloquea cierres accidentales mientras el hilo de build sigue activo.

## 4.0.0-qa6 — 2026-07-23

### Supervivencia del proceso

- El acceso directo inicia un supervisor externo y no directamente el proceso lector.
- Si el proceso lector termina inesperadamente, se reinicia con el COM guardado y sin repetir la calibración.
- La opción **Salir** crea una marca explícita para detener también al supervisor.
- Se agregaron archivos persistentes para excepciones Python y fallos nativos.
- El actualizador suspende temporalmente el reinicio mientras reemplaza archivos.

### Portapapeles e instancia única

- La escritura deja de administrar memoria `HGLOBAL` manualmente y utiliza `pyperclip`.
- Se conservan y restauran textos previos cuando es seguro hacerlo.
- Los formatos no textuales se respetan y fuerzan el respaldo Unicode.
- Los manejadores de mutex, evento y cierre usan firmas correctas para Windows x64.

## 4.0.0-qa5 — 2026-07-23

### Estrés, permanencia y atajos

- Todos los controles usan pegado atómico por portapapeles como primera opción.
- El respaldo Unicode envía un carácter por vez con pausas controladas.
- Cada pegado espera a que Windows procese el evento antes de cambiar el portapapeles.
- Se agregó una separación mínima entre trabajos para impedir filas mezcladas bajo carga.
- `Ctrl+Alt+C` se registra globalmente y alterna las dos configuraciones favoritas.
- `Ctrl+Alt+Esc` comparte el mismo servicio global y conserva la cancelación de emergencia.
- Un supervisor reinicia automáticamente la cola o el gestor serial si sus hilos terminan.
- Un lector atascado en conexión, lectura o procesamiento fuerza una reconexión.
- La bandeja se vuelve a crear si su backend termina sin una salida manual.

## 4.0.0-qa4 — 2026-07-23

### Escritura en Windows

- Se corrigió la estructura `INPUT` usada por `SendInput` en Windows x64/x86.
- El portapapeles Win32 ahora declara correctamente manejadores y punteros de 64 bits.
- Los controles modernos no verificables, como el Bloc de notas de Windows 11, usan entrada Unicode directa.
- Los controles clásicos y WinForms conservan el pegado rápido, con fallback Unicode si falla.
- Una configuración con reemplazo explícito puede usar `Ctrl+A` sobre la ventana exacta aunque el control sea XAML.
- Los fallos de la cola actualizan el último error visible en el panel DMS.

## 4.0.0-qa3 — 2026-07-23

### Calibración, interfaz e instalador

- El inicio muestra una calibración guiada y selecciona primero el último COM guardado.
- Cada puerto se prueba durante 10 segundos; si ninguno responde se permite reintentar o cerrar.
- La lectura usada para calibrar solo valida el puerto y nunca se envía al formulario.
- Se agregó un panel de control con la misma paleta oscura y roja del dashboard.
- El instalador ofrece accesos directos de escritorio e inicio automático con Windows, ambos seleccionados por defecto.
- El SBOM usa `cyclonedx-py` o `python -m cyclonedx_py` y no bloquea el Setup si falla.
- El catálogo empaquetado se valida contra los siete formatos de cédula/documento esperados.
- GitHub Actions separa pruebas y Ruff y publica un reporte de lint descargable.

## 4.0.0-qa2 — 2026-07-22

### Licencias y dashboard

- El dashboard principal usa directamente el pipeline seguro; se eliminó el wrapper duplicado.
- Crear un cliente genera inmediatamente `clientes/<CLIENT_ID>/licencia.key` firmado y su clave pública.
- Renovar o extender reemplaza atómicamente la licencia firmada.
- Se agregó exportación directa para copiar `licencia.key` y `assets/license_public_key.pem` a una instalación.
- Dashboard, instalador y renovación usan una única raíz Ed25519.
- Se eliminaron emisores y capturadores antiguos duplicados que ya no formaban parte del runtime.

## 4.0.0-qa1 — 2026-07-22

### Seguridad y confiabilidad

- Nuevo runtime compuesto sin monkey patches por importación.
- Licencias offline Ed25519 con UTC estricto, renovación y protección de reloj.
- Gestor serial con estados, identidad USB, primera lectura no destructiva y reconexión.
- Cola tipada con HWND exacto, timeout, backpressure, pausa, cancelación y generaciones.
- Escritor universal con foco exacto, políticas de vacío, acciones configurables, validación por tipo y cancelación de emergencia.
- Portapapeles restaurado cuando es seguro; fallback `SendInput` Unicode.
- Configuración schema v2 con migración, validación, backups y escritura atómica.
- TSE fuera del listener, URL allowlist y límites de red.
- Logs estructurados, redactados y rotativos.
- Updater firmado con hashes, backup, reemplazo atómico, smoke test y rollback.
- Build limpio, nombres estables, versiones unificadas, SBOM y CI Windows/Linux.

### Pruebas

- 56 pruebas automatizadas y simuladas; 2 pruebas condicionadas omitidas.
- Matriz física preparada; resultados físicos aún pendientes.
