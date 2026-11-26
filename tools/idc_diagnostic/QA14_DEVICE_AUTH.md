# IDC QA14 — DeviceSignature de laboratorio
Base: QA13, PR #38 (24 pruebas confirmadas en Windows).

- Comprueba IssuerAuth y digests sintéticos antes de validar DeviceSignature.
- Usa la clave pública P-256 incluida en el MSO firmado, nunca una clave
  suministrada independientemente en la respuesta.
- Verifica COSE Sign1 ES256 con payload separado sobre DeviceAuthenticationBytes,
  vinculado al transcript de laboratorio de la sesión actual y al docType.
- Rechaza sustitución de clave, firma modificada, docType incorrecto, reutilización
  de firma en una sesión nueva, namespaces no vacíos, algoritmo no admitido,
  atributos modificados y ancla incorrecta.
- Solo se aceptan transcripts ficticios generados por el lector de laboratorio.
  No hay BLE, COM, extracción de datos reales ni cambios al programa principal.
- device_auth_verified, verified_identity e idc_verification_available quedan
  siempre falsos. No es un verificador de producción.

## Ejecutar
```cmd
py -m pytest tests/unit/test_idc_issuer_auth.py tests/unit/test_idc_signed_items_lab.py tests/unit/test_idc_device_auth_lab.py -q
```
Se esperan 35 casos (24 previos + 11 nuevos). No requiere teléfono.

## Limitaciones y siguiente etapa
El resultado no prueba interoperabilidad real. Reutilizar el mismo transcript
no se impide en este módulo sin estado: la futura capa de sesión debe generar
un transcript nuevo por intento, consumirlo una sola vez y gestionar replay.
No se implementa DeviceMac, ReaderAuth, revocación, ni política de confianza IDC.
Siguiente: perfil documentado de IDC, anclas autenticadas y pruebas de sesión
con material de prueba autorizado, antes de integración de producción.
