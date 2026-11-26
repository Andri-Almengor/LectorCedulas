# QA20 — diagnóstico de namespaces y DeviceMac

QA19 confirmado: 40 pruebas; respuesta real mDL, IssuerAuth y DeviceMac
presentes, namespace solicitado y país emisor ausentes. No se han
verificado firmas ni autenticidad de la credencial.

QA20 mantiene la solicitud exacta de issuing_country y el consentimiento
de QA19. Distingue namespaces de emisor ausentes, vacíos o alternativos;
inspecciona la estructura de namespaces del dispositivo y errores por
atributo, así como la forma no verificada del MSO y COSE_Mac0.
Los booleanos no exponen identificadores alternativos, atributos, valores,
certificados, claves ni material de sesión. HMAC256 shape no valida el MAC;
P256 shape no valida la clave ni el punto de curva. No se cambia main.

```cmd
py -m pytest tests/unit/test_idc_mdl_namespace_mac_shape.py tests/unit/test_idc_mdl_response_shape.py tests/unit/test_idc_photoid_candidate.py tests/unit/test_idc_ble_session_lab.py -q
py -m tools.idc_diagnostic.photoid_candidate --port COM5 --consent --allow-mdl-candidate --ble-scan-seconds 30
```
50 casos esperados (40 + 10). Usar QR nuevo del titular presente.
Cancelar si pide datos diferentes o no hay consentimiento.
Compartir únicamente JSON categórico.
