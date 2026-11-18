# Primer QR de IDC: informe de metadatos recibido

Fecha: 18 de noviembre de 2026. Muestra aportada voluntariamente para
prueba de interoperabilidad, **sin payload original**.

```json
{
  "schema_version": 1,
  "purpose": "format_diagnostic_only",
  "verified_identity": false,
  "raw_bytes": 301,
  "framed_bytes": 299,
  "classification": "mdoc_candidate",
  "utf8": true,
  "base64url_chars": 294,
  "base64url_valid": true,
  "decoded_bytes": 220,
  "cbor_initial_major_type": "map",
  "cbor_indefinite_length": false
}
```

## Evidencia y limitaciones

- El lector capturó un QR de texto con esquema `mdoc:` y 294 caracteres Base64URL.
- Se decodificaron 220 bytes, cuyo primer byte corresponde a un mapa CBOR.
- Este informe **NO comprueba** que los 220 bytes formen CBOR completo ni que
  correspondan a una versión concreta de ISO 18013, ISO 23220 o GET Group.
- En ISO/IEC TS 23220-4:2026, la estructura de engagement puede ser un mapa
  CBOR con claves numéricas. Es una hipótesis compatible con la primera
  observación, pero no confirma el perfil del TSE.
- No se puede concluir aún que BLE sea requerido ni que sea posible leer
  nombre o cédula directamente del QR.
- No se incluyó QR, cédula, token, clave temporal ni URL en el repositorio.

## Próximo paso

Repetir el escaneo con el diagnóstico ampliado del PR #22. El nuevo JSON
incluye forma CBOR interna y posibles métodos de comunicación sin divulgar
sus parámetros. Confirmar con TSE / GET Group SDK y certificados oficiales.
