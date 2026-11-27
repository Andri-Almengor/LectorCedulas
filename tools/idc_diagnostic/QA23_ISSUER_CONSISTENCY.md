# QA23 — consistencia de firma de emisor (no confianza)
QA22: 6/6 vector ISO y 71/71 acumuladas confirmadas en Windows.
El MAC real no coincidió pese al payload esperado; no cambiar la fórmula
ni ensayar variantes no normativas. En paralelo verificar si IssuerAuth
es consistente con el certificado de firmante presentado por la IDC.
RFC 9052 sección 4.4 y RFC 9360: la firma matemática no autentica el emisor;
x5chain es material no confiable hasta validar una ruta contra un ancla
independiente. No se exporta ni se convierte en ancla.
https://www.rfc-editor.org/rfc/rfc9052.html
https://www.rfc-editor.org/rfc/rfc9360.html

Se informa solo mediante booleanos: forma COSE, algoritmo, cadena de uno
o varios certificados, forma/fecha del certificado, coincidencia de la
firma con la clave del certificado presentado, docType y fechas del MSO.
ES256/384/512 reconocidos; los nuevos tests cubren ES256, no certifican
interoperabilidad con todos los algoritmos. No verifica revocación,
cadena, atributos ni autenticidad de IDC. No cambia los flags finales
issuer_signature_verified, verified_identity, device_auth_verified ni
iaca_trust_anchor_validated. No altera petición de país emisor ni consentimiento.
No guardar certificados, QR o datos personales ni cambiar main.

```cmd
py -m pytest tests/unit/test_idc_issuer_consistency.py tests/unit/test_idc_iso_annex_d.py tests/unit/test_idc_device_mac_precheck.py tests/unit/test_idc_mdl_namespace_mac_shape.py tests/unit/test_idc_mdl_response_shape.py tests/unit/test_idc_photoid_candidate.py tests/unit/test_idc_ble_session_lab.py -q
```
83 casos esperados (71 + 12). Luego, solo si el titular autoriza la misma
prueba de país emisor y se cumplen los requisitos de la aplicación:
```cmd
py -m tools.idc_diagnostic.photoid_candidate --port COM5 --consent --allow-mdl-candidate --ble-scan-seconds 30
```
Cancelar si solicita otros datos. Compartir solo JSON. Si el verificador
oficial también falla, solicitar soporte TSE: no insistir con solicitudes
de atributos ni modificar mecanismos de autorización.
