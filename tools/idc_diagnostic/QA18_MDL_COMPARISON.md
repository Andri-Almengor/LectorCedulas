# QA18 — comparación limitada de perfil mDL
QA17: 25 pruebas de transporte/candidato confirmadas. Photo ID devolvió
status 0, data_not_returned y ausencia de documento; sin ventana de
autorización y con cierre automático del QR. No identifica la causa.
Se compara exclusivamente el perfil público mDL ISO 18013-5, documentado
en https://developers.google.com/wallet/identity/verify/supported-credential-attributes .
No hay evidencia de que la IDC sea una licencia ni use este docType.
No se cambia el consentimiento, no se añaden datos personales,
no se automatizan intentos ni se admiten identificadores arbitrarios.

```cmd
py -m pytest tests/unit/test_idc_photoid_candidate.py tests/unit/test_idc_ble_session_lab.py -q
py -m tools.idc_diagnostic.photoid_candidate --port COM5 --consent --allow-mdl-candidate --ble-scan-seconds 30
```
30 pruebas esperadas. Probar una vez con QR nuevo del titular presente;
cancelar si pide otros datos o credenciales de lector no disponibles.
Si el resultado vuelve a ser data_not_returned, no seguir adivinando:
comparar con Verificador IDC oficial en otro dispositivo, con consentimiento.
No compartir capturas ni PII; solo si muestra autorización, si termina y
si informa éxito. No verifica autenticidad de credencial ni cambia main.
