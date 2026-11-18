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

El segundo escaneo ya confirmó métodos anunciados BLE y NFC. Consultar la segunda lectura más abajo. Confirmar con TSE / GET Group el SDK y los certificados oficiales.

## Segunda lectura real — diagnóstico CBOR ampliado

Aportada el 18 de noviembre de 2026. Solo se almacenan metadatos:

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
  "cbor_indefinite_length": false,
  "cbor_structure_decoded": true,
  "cbor_profile_hint": "iso_23220_map_shape_candidate",
  "transport_candidates": ["BLE", "NFC"],
  "cbor_root_items": 4,
  "known_engagement_fields_present": [0, 1, 2, 3]
}
```

### Interpretación precisa

- El código real contiene un engagement `mdoc:` que decodifica a un **mapa CBOR bien formado**.
- El detector identifica una estructura **compatible en forma** con ISO/IEC TS 23220;
  no valida formalmente dicho estándar ni garantiza la identidad del emisor.
- La estructura **anuncia BLE y NFC** en el campo de métodos de comunicación.
- La presencia del campo `3` no demuestra consulta remota obligatoria ni coste
  por lectura. No divulgar su valor sin política autorizada.
- El lector actual **sí capturó el QR**. Quedan pendientes la disponibilidad
  del radio BLE de Windows, el enlace con el móvil, los certificados de
  confianza del TSE, el SDK autorizado y la verificación criptográfica.
- Los atributos de la persona NO se extrajeron ni se verificaron.
- Un segundo informe con igual longitud puede proceder del mismo QR, por
  lo que estas dos mediciones no demuestran sesiones separadas o frescura.

### Próxima fase

1. Comprobar hardware BLE con la guía `docs/IDC_OFFLINE_BLE_READINESS.md`.
2. Pedir a TSE/GET Group especificación de transporte y SDK de verificación
   offline autorizado en Windows, incluyendo distribución de confianza.
3. Crear contrato de integración del proveedor en rama futura `qa10`,
   que permanezca completamente **fail closed** hasta validar emisor,
   integridad, sesión, consentimiento y política de vigencia.
4. Mantener lectura física y TSE QR URL como rutas independientes.
