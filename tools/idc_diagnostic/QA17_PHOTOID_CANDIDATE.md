# QA17 — hipótesis pública ISO Photo ID
Base QA16: 57 pruebas confirmadas.
La ficha Google Play de IDC declara cumplimiento ISO 18013-5:
https://play.google.com/store/apps/details?id=com.getgroup.costarica.mid.citizen
El perfil público ISO Photo ID y el atributo issuing_country están documentados en:
https://developers.google.com/wallet/identity/verify/supported-credential-attributes
Esto NO confirma que IDC use ese perfil. Una prueba negativa no descarta mdoc
ni revela si requiere ReaderAuth. Una respuesta positiva estructural tampoco
demuestra que se entregó el atributo solicitado o que es auténtico.

Prueba exclusivamente con la propia IDC o titular presente que consienta.
No simular autorización, no solicitar nombres, números ni fotos. Si el teléfono
pide otros datos o autenticación de lector no disponible, cancelar.
No guardar QR, respuesta, certificados ni valores; compartir solo JSON.
No modifica la app principal, no integra datos ni valida identidad.

```cmd
py -m pytest tests/unit/test_idc_photoid_candidate.py -q
py -m tools.idc_diagnostic.photoid_candidate --port COM5 --consent --allow-photoid-candidate --ble-scan-seconds 30
```
6 pruebas nuevas. Cerrar app principal, activar Bluetooth, generar QR nuevo.
El transporte mantiene el límite de respuesta existente y no interpreta
atributos. El certificado de confianza autenticado sigue siendo necesario.
