# Changelog

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
