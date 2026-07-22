# Privacidad y logging

## Política

El Lector procesa datos personales únicamente para transferirlos al formulario elegido. El modo normal no guarda RAW, nombres, cédulas completas, tokens ni querystrings.

## Eventos permitidos

- ID secuencial del trabajo.
- estado del lector/cola.
- COM, VID y PID del dispositivo.
- identificador de configuración y generación.
- HWND/PID técnicos del target.
- tiempos y códigos de error.
- `license_id` y `client_id` administrativos, no datos del titular del documento.

## Redacción

- Identificadores numéricos: solo últimos cuatro dígitos cuando aparecen accidentalmente.
- Tokens: `[REDACTED]`.
- URLs: sin querystring ni fragmento.
- Nombres: no están en allowlist y se descartan.

## Retención

`RotatingFileHandler` usa 2 MB por archivo y 10 backups por defecto. La organización debe definir un periodo operativo; recomendación inicial: máximo 30 días y limpieza al cerrar incidentes.

## Diagnóstico

El guardado de RAW no está habilitado en el runtime normal. Cualquier futuro modo diagnóstico debe:

1. estar desactivado por defecto;
2. solicitar consentimiento explícito;
3. mostrar qué se guardará y por cuánto tiempo;
4. usar fixtures sintéticos cuando sea posible;
5. permitir borrar diagnósticos desde bandeja;
6. restringir ACL de la carpeta.

## Portapapeles

Si contiene solo formatos de texto restaurables, se guarda y restaura. Si contiene imágenes, archivos u otros formatos, no se modifica y se usa `SendInput` Unicode. El historial de portapapeles o software de terceros puede conservar contenidos fuera del control de la aplicación.
