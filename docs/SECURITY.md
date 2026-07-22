# Modelo de amenazas

## Activos

- Datos personales extraídos del documento.
- Integridad de configuraciones y navegación.
- Licencia y claves públicas.
- Binarios, setup y paquetes de update.
- Control del teclado, foco y portapapeles.

## Límites de confianza

1. Lector USB/COM y driver.
2. Aplicación local y usuario interactivo.
3. Ventana objetivo de un proceso externo.
4. Endpoint TSE.
5. Dashboard/build host.
6. Instalador y updater.

## Amenazas y controles

| Amenaza | Control |
|---|---|
| Suplantación de COM | identidad VID/PID/serial/fabricante más primera lectura reconocida |
| Lectura maliciosa o truncada | límites, silencio real, parser allowlist y validación antes de encolar |
| URL parecida/SSRF | HTTPS exacto, hostname allowlist, puerto 443, sin credenciales, sin redirects |
| Respuesta TSE enorme | streaming y límite 512 KB |
| Captura de PII en logs | allowlist de campos técnicos, redacción y rotación |
| PII en clipboard | restauración; no modifica formatos no restaurables; fallback SendInput Unicode |
| Escritura en ventana equivocada | HWND/PID/root exactos y foreground antes de cada acción |
| Dos ventanas del mismo proceso | no se acepta PID como identidad suficiente |
| Manipulación de config | esquema estricto, backup, atomic replace, fallo cerrado |
| Manipulación de licencia | Ed25519, payload canónico, UTC, anti-clock, product/client/license IDs |
| Copia a otro equipo | binding opcional a `installation_id`; se deja desactivado si no existe proceso de reactivación |
| Update malicioso | manifest Ed25519, SHA-256, product/version, path traversal block |
| Downgrade | comparación semántica y bloqueo por defecto |
| DLL hijacking | instalar en Program Files; no cargar DLL por CWD; builds onefile y paths explícitos |
| Symlink/path traversal | rutas de manifest normalizadas; no `..`, absolutas, drive ni datos preservados |
| Secure Desktop/UAC | no intenta escribir; target/foco falla cerrado |
| Proceso elevado vs no elevado | Windows puede bloquear input; se informa fallo, no se fuerza elevación |
| Usuarios/sesiones múltiples | mutex/evento global; pruebas RDP y cambio de usuario pendientes |
| Temporales | stage bajo directorio controlado, nombres aleatorios y limpieza `finally` |
| Clave privada filtrada | solo `%LOCALAPPDATA%/.../secrets`; `.gitignore`; nunca copiada a app/setup |

## Claves y firmas

- Licencia: par Ed25519 independiente.
- Update: par Ed25519 independiente.
- Authenticode: pendiente de certificado corporativo y almacén seguro.
- La pérdida de una clave privada exige rotación de clave pública y plan de migración firmado.

## Riesgos residuales

- Un malware en la misma sesión puede capturar teclado/clipboard; el producto reduce persistencia, no puede proteger una sesión Windows comprometida.
- UI Automation no está incorporado para todos los frameworks; controles no legibles no se marcan como verificados.
- Administradores de portapapeles pueden conservar historial; se documenta al usuario y se recomienda desactivar historial en estaciones de alta sensibilidad.
