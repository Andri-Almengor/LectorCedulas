# Changelog

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
