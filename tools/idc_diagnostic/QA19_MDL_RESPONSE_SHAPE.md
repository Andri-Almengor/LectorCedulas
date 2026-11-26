# QA19 — inspección estructural del documento recibido
Base QA18: primera respuesta de campo con mDL, status 0, un documento y
ningún error. No demuestra aún que el documento coincida con la solicitud.

Mantiene la misma petición autorizada de issuing_country. No solicita
nombre, número de cédula ni fotografía. Después de autenticar AES-GCM,
revisa si el docType y namespace coinciden, si el atributo está presente
con forma de código de dos letras y si aparecen estructuras de firma/MAC.
Solo devuelve booleanos. No devuelve valores, certificados, claves o blobs.

Presencia de IssuerAuth y DeviceSignature/DeviceMac no implica validez.
No valida digests, MSO, DeviceAuth ni anclas de confianza reales.
No se modifica la aplicación principal ni se realiza registro automático.

```cmd
py -m pytest tests/unit/test_idc_mdl_response_shape.py tests/unit/test_idc_photoid_candidate.py tests/unit/test_idc_ble_session_lab.py -q
py -m tools.idc_diagnostic.photoid_candidate --port COM5 --consent --allow-mdl-candidate --ble-scan-seconds 30
```
40 casos esperados (30 anteriores + 10 nuevos). Usar QR nuevo, titular
presente y consentimiento explícito. Cancelar si pide datos diferentes.
Compartir solo JSON. La siguiente fase dependerá de la forma observada;
no asumir confianza a partir de un certificado presentado por el dispositivo.
