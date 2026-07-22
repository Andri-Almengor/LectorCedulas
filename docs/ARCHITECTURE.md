# Arquitectura del Lector de Cédulas DMS

## Principios

1. Un frame serial aceptado nunca cambia de configuración ni de ventana silenciosamente.
2. El listener serial no escribe formularios ni realiza I/O de red.
3. La cola es el único punto que autoriza una escritura.
4. La identidad de ventana es `HWND + PID + root HWND`; el título es informativo.
5. Configuración, perfil y destino son snapshots del trabajo.
6. Fallar cerrado es preferible a escribir en otra aplicación.
7. Los valores personales no se registran.

## Componentes

### `Application`

Compone los servicios, valida licencia antes de iniciar, mantiene bandeja, notificaciones y cierre cooperativo. No reduce prioridad del proceso.

### `SerialManager`

- Estados explícitos.
- Descubrimiento ordenado por último dispositivo e identidad USB.
- Baudrates configurables.
- Lectura por silencio con límites.
- Reconexión con backoff.
- La primera lectura reconocida se procesa y confirma el dispositivo.
- Métricas: bytes, frames, aceptados, rechazados, tiempo y reconexiones.

### `ParserService`

Detecta TSE URL y mDoc sin red, valida URL exacta y delega formatos históricos a `lector_core`. `TseEnrichmentService` se ejecuta en pool, bloquea redirects, limita respuesta y usa caché breve en memoria.

### `ConfigurationService`

- Esquema v2.
- Migración compatible desde `{nombre, campos}`.
- Escritura atómica y backup.
- Rechaza corrupción, duplicados, etiquetas desconocidas y valores no finitos.
- No activa otro formulario automáticamente.

### `ScanQueue`

- `ScanJob` tipado.
- Capacidad 64 por defecto.
- Backpressure no bloqueante.
- Pausa, reanudación, vaciado y cancelación.
- Al cambiar configuración cancela trabajo actual y pendientes anteriores.

### `FormWriter`

- Recibe target exacto; nunca recaptura otra ventana.
- Verifica `IsWindow`, PID, root y foreground antes de acciones.
- Usa portapapeles solo cuando puede restaurar formatos de texto; si existen formatos ajenos, usa `SendInput` Unicode.
- Libera modificadores en `finally`.
- No usa `Ctrl+A` sin control exacto legible.
- Políticas de vacío y acciones configurables.
- Validación estricta por tipo.
- Métricas totales y por campo sin valores.

### Licencia y updates

Licencias y manifests usan envelopes con payload canónico y firma Ed25519. Las claves privadas se generan en `%LOCALAPPDATA%\DMS\LectorCedulas\secrets` por el dashboard seguro. Cliente, setup y repo contienen solo claves públicas.

## Esquema de configuración v2

```json
{
  "schema_version": 2,
  "id": "formulario-visitantes",
  "nombre": "Formulario Visitantes",
  "perfil_escritura": "equilibrada",
  "validar_escritura": true,
  "reemplazar_contenido": false,
  "accion_final": "none",
  "campos": [
    {
      "dato": "Cedula",
      "tabuladores": 0,
      "politica_vacio": "cancelar",
      "valor_predeterminado": "",
      "reemplazar": false,
      "validacion": "cedula",
      "comparacion_normalizada": false,
      "espera_adicional": 0.0,
      "accion_posterior": "tab"
    }
  ]
}
```

`tabuladores` significa movimientos **adicionales antes del campo**. `accion_posterior` gobierna cada transición no final y `accion_final` gobierna el último campo. Las configuraciones antiguas migran con acción final `Tab` para conservar el comportamiento histórico.

## Contratos de concurrencia

- Solo `DMSScanQueue` llama `FormWriter.write`.
- `ScanJob` no se modifica salvo estado/resultado técnico.
- Un cambio de configuración incrementa generación y cancela jobs anteriores.
- El pool de parsers está limitado a cuatro workers y 128 trabajos admitidos.
- La saturación se notifica y no bloquea el COM.

## Cierre y actualización

`InstanceControl` crea un mutex y un evento global. El updater solicita cierre mediante el evento, espera desbloqueo, verifica manifest/hashes, prepara stage y backup, reemplaza atómicamente, ejecuta smoke test y hace rollback ante error.
