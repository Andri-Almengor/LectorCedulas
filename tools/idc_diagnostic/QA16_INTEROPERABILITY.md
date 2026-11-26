# QA16 — preparación de interoperabilidad real IDC
Fecha: 2026-11-26. Base: QA15, PR #40, 51 pruebas confirmadas.

## Hallazgos públicos
- TSE: https://www.tse.go.cr/idc/ confirma verificador Windows gratuito.
- GET Group y RACSA participaron en la implementación:
  https://www.getgroup.com/news/costa-rica-launches-its-first-ever-national-digital-identity-application
  https://www.racsa.go.cr/blog/identidad-digital-costarricense-impulsa-competitividad-del-pais-y-revoluciona-acceso-a-servicios/
- El fabricante ofrece SDK/API y motor Windows para credenciales móviles:
  https://www.getgroup.com/products/get-mobile-id
  https://latam.getgroup.com/solutions/get-mobile-verify/
- No se ha confirmado que el SDK comercial permita verificar IDC Costa Rica
  offline, ni precio, condiciones de licencia o esquema específico.
- Los perfiles ISO genéricos no prueban qué docType o namespace usa IDC.
  No se encontró publicación abierta del perfil exacto o anclas autenticadas.

## Próximo paso de campo
Solicitar a GET Group/RACSA el perfil de documento, atributos mínimos,
ReaderAuth, anclas y distribución autenticada, revocación offline,
vector de interoperabilidad sin datos reales y SDK Windows de evaluación.
Confirmar requisitos de licencia y posibilidad de uso sin Internet.
No pedir claves privadas de emisor ni credenciales de ciudadanos.

## Diagnóstico local
```cmd
py -m tools.idc_diagnostic.profile_preflight
```
Sin material devuelve profile_required y código 2. Una vez recibido material
técnico por canales autenticados, guardarlo fuera del repositorio:
```cmd
py -m tools.idc_diagnostic.profile_preflight --profile C:\IDC\profile.json --anchor-der C:\IDC\iaca.der --anchor-pin-file C:\IDC\pin.txt
```
El JSON de perfil QA15 requiere schema_version, doc_type, namespace,
name_element, number_element y reader_auth. No se incluyen valores
inventados. El modelo provisional admite un nombre y un namespace;
adaptar cuando llegue el esquema real.
El archivo pin.txt debe contener una huella SHA-256 del DER obtenida
por un canal autenticado independiente, no calculada del candidato
y luego aceptada como prueba de procedencia.
Código 0 significa solo preparación estructural; no identidad verificada.
No adjuntar materiales, certificados privados, QR o PII a GitHub.
No hay tráfico de red, BLE ni COM en este comando.

## Pruebas acumuladas
```cmd
py -m pytest tests/unit/test_idc_issuer_auth.py tests/unit/test_idc_signed_items_lab.py tests/unit/test_idc_device_auth_lab.py tests/unit/test_idc_profile_readiness.py tests/unit/test_idc_profile_preflight.py -q
```
57 esperadas. No modifica la aplicación principal. No fusionar a main.
