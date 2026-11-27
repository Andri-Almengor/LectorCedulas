# QA24 — ancla de confianza suministrada externamente
Campo QA23: firma ES256 coincide con el certificado presentado, MSO vigente,
un certificado, MAC real no coincide y país no divulgado. Esto NO autentica
al TSE. QA23 pytest aún no confirmado.
La prueba permite suministrar un certificado IACA público DER y su huella
SHA-256 DER obtenida por canal autenticado independiente. No usar certificados
capturados de la sesión como anclas. No inventar pins ni tratar una huella
calculada localmente como evidencia independiente. Se comprueba el hash,
forma de CA, autofirma y vigencia antes de iniciar BLE, y se aplica el
precheck directo ES256 previamente implementado. No valida revocación ni
política completa, ni cambia ningún flag de identidad final.
No extraer ni almacenar datos personales. No cambiar solicitud, consentimiento
ni app principal. Los archivos oficiales permanecen locales fuera del repo.

```cmd
py -m pytest tests/unit/test_idc_pinned_issuer.py tests/unit/test_idc_issuer_consistency.py tests/unit/test_idc_iso_annex_d.py tests/unit/test_idc_device_mac_precheck.py tests/unit/test_idc_mdl_namespace_mac_shape.py tests/unit/test_idc_mdl_response_shape.py tests/unit/test_idc_photoid_candidate.py tests/unit/test_idc_ble_session_lab.py -q
```
93 casos esperados (83 + 10).

Solo una vez obtenidos y autenticados los archivos públicos del TSE,
y aclarado el flujo autorizado de presentación:
```cmd
py -m tools.idc_diagnostic.photoid_candidate --port COM5 --consent --allow-mdl-candidate --anchor-der "C:\IDC\iaca.der" --anchor-pin-file "C:\IDC\iaca-sha256.txt"
```
Rutas de ejemplo; no existen aún. No repetir la presentación hasta resolver
la autorización o disponer de material nuevo. Solicitar al TSE el ancla
pública, huella independiente, política de vigencia/revocación y aclaración
de ReaderAuth y de la interoperabilidad del verificador oficial.
