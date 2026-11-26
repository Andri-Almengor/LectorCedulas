# QA21 — DeviceMac y error por atributo
Base QA20: respuesta real mDL con MSO decodificable, namespace estándar
y otro namespace en valueDigests; no hubo atributos divulgados.
La forma MAC no pasó la comprobación anterior.

Se conserva exactamente la solicitud de issuing_country. Se distinguen
campos COSE, algoritmo, payload separado, tag vacío o de 32 bytes y error
del atributo solicitado. No se revelan códigos privados, campos ni datos.
Si la forma es estrictamente compatible, se calcula EMacKey con ECDH
entre la clave efímera del lector y la clave estática del MSO, salt SHA-256
del SessionTranscriptBytes e info EMacKey, como en ISO 18013-5:2021.
El resultado solo demuestra consistencia con una clave aún no autenticada.
No se acepta ninguna identidad, no se altera el consentimiento, no se
solicitan atributos adicionales ni se modifica la aplicación principal.
La clave del MSO no es un ancla de confianza.

Fuente de referencia independiente:
https://github.com/openwallet-foundation/multipaz/blob/main/multipaz/src/commonMain/kotlin/org/multipaz/mdoc/response/DeviceResponseParser.kt

```cmd
py -m pytest tests/unit/test_idc_device_mac_precheck.py tests/unit/test_idc_mdl_namespace_mac_shape.py tests/unit/test_idc_mdl_response_shape.py tests/unit/test_idc_photoid_candidate.py tests/unit/test_idc_ble_session_lab.py -q
py -m tools.idc_diagnostic.photoid_candidate --port COM5 --consent --allow-mdl-candidate --ble-scan-seconds 30
```
60 pruebas esperadas; QA20 no confirmado por pytest.
Usar QR nuevo, titular presente, consentimiento explícito; cancelar si solicita
datos distintos. Si el MAC no tiene forma estándar no intentar forzarlo.
Comparar con Verificador IDC oficial en otro teléfono. No compartir datos
personales. Falta obtener anclas auténticas y resolver divulgación legítima.


## Ajuste QA21.1 — diagnóstico de payload no nulo

Resultado de campo QA21: alg 5 protegido y tag de 32 bytes, pero payload
no nulo; el error del país emisor es data_not_returned. RFC 9052 distingue
bstr de nil; ISO DeviceMac requiere nil.
https://www.rfc-editor.org/rfc/rfc9052.html#section-6.2

Se clasifica payload bstr vacío, bstr coincidente exactamente con los bytes
de autenticación reconstruidos localmente, o cualquier otra forma.
Solo para bstr vacío o exacto se compara el tag contra el esperado usando
el transcript propio. Nunca se autentica el bstr vacío ni datos arbitrarios.
Incluso si coincide, se mantiene falso el indicador de MAC ISO conforme.
No se modifica la solicitud ni se elude una negativa de divulgación.
Cinco casos adicionales: total esperado 65 para la misma orden pytest.
Realizar control con el verificador oficial; no continuar solicitando
atributos personales sin aclarar el flujo de autorización.
