# QA22 — auditoría focalizada ISO/IEC 18013-5:2021

Base: QA21.1, PR #46. El TSE confirmó por escrito la norma y el desarrollo
independiente, con minimización y sin almacenar datos de la credencial.
No guardar el correo, datos personales o material de credenciales reales
en el repositorio. No se modifica la aplicación principal.

## Hallazgos y pruebas
- Sección 9.1.3.5: ECDH con clave estática MSO y efímera de lector,
  HKDF SHA-256 con salt SHA-256(SessionTranscriptBytes) e info EMacKey,
  HMAC 256/256, contenido separado y AAD vacío. El código coincide con
  esta fórmula y con DeviceResponseParser de Multipaz.
- Se comprobó independientemente el vector público de D.5.1 y D.5.3:
  secreto compartido, EMacKey y tag coinciden byte por byte. La verificación
  aislada se ejecutó con cryptography y framing de bytes, no con el parser.
- Se incorpora el vector de Multipaz (blob 91af0ce314b8e37a008b3463049c048e3130deb9,
  Apache-2.0) en tests/unit/test_idc_iso_annex_d.py. Los seis casos
  prueban el cálculo y la función real; no contienen credenciales de ciudadanos.
  No se incluye DeviceResponse completo ni datos de ejemplo innecesarios.
- La respuesta IDC observada contiene payload adjunto idéntico al esperado,
  pero el tag no coincide. Un payload adjunto no cumple el formato de
  DeviceMac de 9.1.3.5. No relajar ni probar variantes arbitrarias.
- El precheck todavía no es un verificador ISO completo: admite COSE
  etiquetado para diagnóstico (la norma requiere no etiquetado), no
  autentica el MSO, no verifica revocación ni políticas de confianza.
- La devolución del error individual data_not_returned no prueba que
  ReaderAuth sea obligatorio. No intentar obtener atributos sin el flujo
  de consentimiento/autoridad exigido. Falta confirmación del verificador
  oficial con Internet y los certificados de confianza autenticados.

## Fuentes
- ISO/IEC 18013-5:2021, 9.1.3.5 y D.5.1/D.5.3:
  https://law.resource.org/pub/us/cfr/ibr/inc/iec/iec.18013-5.2021.pdf
- https://github.com/openwallet-foundation/multipaz/blob/main/multipaz/src/commonTest/kotlin/org/multipaz/mdoc/TestVectors.kt
- https://github.com/openwallet-foundation/multipaz/blob/main/multipaz/src/commonMain/kotlin/org/multipaz/mdoc/response/DeviceResponseParser.kt

## Ejecutar en Windows
```cmd
py -m pytest tests/unit/test_idc_iso_annex_d.py -q
```
Esperadas 6 pruebas. No requiere COM5, teléfono ni Internet. Después:
```cmd
py -m pytest tests/unit/test_idc_iso_annex_d.py tests/unit/test_idc_device_mac_precheck.py tests/unit/test_idc_mdl_namespace_mac_shape.py tests/unit/test_idc_mdl_response_shape.py tests/unit/test_idc_photoid_candidate.py tests/unit/test_idc_ble_session_lab.py -q
```
71 casos esperados. QA20/QA21 aún pendientes de confirmación acumulada.
No fusionar ni desplegar. La prueba oficial entre dos teléfonos debe
confirmar si la presentación con Internet funciona, antes de más intentos IDC.
