# Punto de recuperación anterior a la IDC

- Fecha: 2026-11-18 (America/Costa_Rica).
- Repositorio: `Andri-Almengor/LectorCedulas`.
- Versión de producción declarada en el repositorio: **4.0.0-qa8** (no prueba qué versión está instalada).
- Último PR integrado en `main`: **#21**.
- SHA fijo anterior a estos cambios:
  `648bd1935557c2b8bc356ddc88d0c713e488bc9f`
- Rama de respaldo creada: `backup/pre-idc-4.0.0-qa8-2026-11-18`.
- Rama experimental: `feature/idc-offline-discovery-qa9`.
- Estado: NO modificar `main` ni fusionar la PR experimental antes de pruebas físicas.

## Restauración

Para consultar la versión original:
`git checkout backup/pre-idc-4.0.0-qa8-2026-11-18`

Para construir la aplicación anterior, seguir el procedimiento de instalación de ese
commit. **No** hacer `git reset --hard` en `main` sin un plan de cambios compartidos.

Este respaldo Git conserva el código fuente y el historial, NO realiza copias de:
- datos del cliente, licencias o secretos guardados fuera del repositorio;
- ejecutables, instaladores o versiones instaladas en los equipos;
- configuraciones locales ignoradas por Git.

Antes de reemplazar un equipo operativo, exportar aparte su configuración y licencia.
