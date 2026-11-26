# IDC QA13 — integridad de atributos firmados (laboratorio)
Base experimental: PR #36. No depende de la guía externa del PR #37.

## Qué cambia
- Verificación de la firma IssuerAuth con ancla externa mediante el precheck existente.
- Validación SHA-256 de los bytes CBOR originales de los dos atributos ficticios.
- Rechazo de elementos ausentes, adicionales, duplicados, alterados, IDs desconocidos,
  CBOR ambiguo o sobrante, perfiles diferentes y anclas incorrectas.
- El perfil fijo org.example.sample no solicita ni procesa datos reales de la IDC.
- No hay cambios en COM, BLE, interfaz, instalación ni lectura de cédulas físicas.

## Pruebas locales (Windows, desde la raíz)
```cmd
py -m pip install -r requirements-dev.txt
py -m pytest tests/unit/test_idc_issuer_auth.py tests/unit/test_idc_signed_items_lab.py -q
```
No se necesita teléfono ni lector COM5. No compartir certificados ni datos personales.

## Alcance
La aprobación solo significa que los atributos sintéticos presentados corresponden
a los digests de un MSO con firma parcialmente prevalidada. No se afirma la
verificación de todos los atributos no divulgados, DeviceAuth, revocación ni identidad.
La validación de firma/cadena heredada sigue limitada al perfil directo IACA/DS.
El módulo acepta bytes originales de cada tag 24; la futura integración deberá
extraerlos sin recodificarlos. La validación estricta CBOR requiere cbor2 6.3.0,
ya fijado en requirements-dev.txt.

## Siguiente etapa
DeviceAuth sintético vinculado al transcript y a la clave pública del MSO,
pruebas de replay y de sustitución de clave. Después, confirmar el perfil real
y material de confianza autenticado, consentimiento y política de revocación.
No desplegar ni fusionar a main.
