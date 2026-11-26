# Diagnóstico QR IDC — etapa experimental 4.0.0-qa9

**Este programa NO verifica la identidad, NO valida firmas y NO registra visitantes.**
No instala drivers, no se comunica con el TSE, no usa la red y no escribe en Lenel.
Es independiente de la aplicación principal. Ejecútalo con el lector principal **cerrado**,
porque un mismo puerto COM no debe abrirse simultáneamente desde dos programas.

## Preparación (Windows)

Instalar Python 3.12+ y las dependencias existentes del repositorio:

```powershell
py -m pip install pyserial==3.5
py -m tools.idc_diagnostic --list-ports
```

Para un lector conectado al puerto COM (usar el puerto real):

```powershell
py -m tools.idc_diagnostic --port COM3 --baudrate 9600 --output diagnosticos/idc_metadatos.json
```

Antes de usar `--output`, crear la carpeta local `diagnosticos`. Está ignorada por Git.
Sin `--output`, solo se muestra el resultado en la consola.

Para un lector que funciona como teclado (HID):

```powershell
py -m tools.idc_diagnostic --keyboard
```

Para una muestra **SINTÉTICA** guardada localmente:

```powershell
py -m tools.idc_diagnostic --sample-file tests/fixtures/idc_mdoc_synthetic.txt
```

El programa espera una lectura y termina. Volver a ejecutarlo para otra lectura.

## Qué compartir

Compartir únicamente el JSON de metadatos, por ejemplo la clasificación,
el tamaño del contenido, la validez base64url y el tipo inicial CBOR.
**No enviar capturas de la IDC, datos personales, QR bruto, URL con tokens,
base64 íntegro, claves, imágenes ni archivos de lectura originales.**
El QR podría incluir parámetros efímeros o material de sesión.

Para un estudio de interoperabilidad más detallado, trabajar con el titular,
el fabricante y el TSE en un entorno autorizado. El programa deliberadamente
NO muestra los bytes originales.

## Limitaciones

- `mdoc_candidate` solo significa que la lectura parece tener el prefijo `mdoc:`;
  NO implica que provenga de una IDC auténtica.
- El diagnóstico ahora analiza la estructura CBOR (límites estrictos), detecta **candidatos** de perfil ISO 23220 (mapa) o ISO 18013 (arreglo) y enumera solo métodos de transporte conocidos. **No certifica conformidad** ni firma.
- `transport_candidates` indica solamente métodos anunciados en una estructura reconocida; no asegura conexión ni compatibilidad con el TSE.
- El lector físico puede limitar el tamaño de datos transferidos. Si se corta,
  estudiar el firmware y sus tiempos; no forzar su integración en producción.
- Conectar por BLE, confiar en certificados y obtener atributos autorizados
  requiere un SDK o implementación verificada y una fase posterior.

## Segunda lectura para confirmar el transporte

Ejecutar nuevamente el mismo comando con la versión que incluye el analizador estructural (PR #23 o posteriores).
El informe incluirá `cbor_structure_decoded`, `cbor_profile_hint`,
`known_engagement_fields_present` y `transport_candidates`.
El perfil es solo una hipótesis estructural; el SDK autorizado debe realizar
la autenticación criptográfica antes de obtener datos de una persona.

## Resultado de campo y siguientes pruebas

La segunda lectura real (solo metadatos, `docs/IDC_REAL_SAMPLE_2026-11-18.md`)
indicó `transport_candidates: ["BLE", "NFC"]` en mapa CBOR.
**No significa que el teléfono y Windows estén emparejados o que se haya
verificado la identidad.** Para continuar, revisar
`docs/IDC_OFFLINE_BLE_READINESS.md`.

## Equipos que pueden NO tener Bluetooth

**Bluetooth no es obligatorio para leer las cédulas físicas actuales.**
El QR de IDC anunció los métodos BLE y NFC, pero no existe todavía un
motor de verificación ni se ha confirmado soporte BLE/GATT de Windows.

Para inspeccionar el estado general del equipo sin detectar celulares próximos:

```powershell
py -m tools.idc_diagnostic --bluetooth-check
```

El JSON solo informa `bluetooth_class_status` (`detected`,
`not_detected`, `unknown` o `not_applicable`). Aun con `detected`,
`ble_session_supported` sigue siendo `not_tested` y
`idc_verification_available` es `false`.

**Sin Bluetooth:** continuar usando el lector DMS para documentos físicos.
Para visitantes con IDC utilizar el verificador oficial disponible en
un dispositivo institucional compatible y hacer registro manual hasta contar
con una integración certificada. Un adaptador BLE USB o lector NFC solo se
justificará después de confirmar el SDK y las especificaciones.

## Corrección del arranque: biblioteca `cryptography` no instalada

En algunas instalaciones, `py -m tools.idc_diagnostic --bluetooth-check`
fallaba antes de abrir el diagnóstico porque `tools/__init__.py` importaba
el constructor de paquetes, que requería `cryptography`.

A partir de esta corrección, el diagnóstico Bluetooth y la clasificación de
muestras pueden arrancar con la **biblioteca estándar de Python**.
Para captura desde lector serial (puerto COM) continúa siendo necesario
`pyserial`; el constructor de instaladores, las licencias y el lector
completo conservan sus dependencias habituales.

Para usar la corrección, descargar el código de la rama del PR de reparación
(o actualizar esa rama con Git) y repetir:

```powershell
py -m tools.idc_diagnostic --bluetooth-check
```

La salida confirma únicamente presencia preliminar de Bluetooth;
no demuestra todavía la compatibilidad BLE con IDC.

## Comprobación real de capacidades BLE del adaptador Windows (opcional)

El informe `--bluetooth-check` prueba únicamente que Windows enumera una
clase Bluetooth. Para comprobar **capacidad Low Energy y roles central/periférico**
se utiliza la API oficial `Windows.Devices.Bluetooth.BluetoothAdapter`
mediante PyWinRT. La biblioteca es **opcional** y no forma parte del lector
principal ni se instala en los clientes automáticamente.

Desde una copia de esta rama, en Windows 10/11 con Python 3.11 o posterior:

```powershell
py -m pip install "winrt-Windows.Devices.Bluetooth==4!10.0.28000.2957"
py -m tools.idc_diagnostic --ble-capabilities
```

El informe NO busca teléfonos, no se empareja, no abre GATT ni almacena
nombre/dirección del adaptador. Los valores
`low_energy_supported`, `central_role_supported` y
`peripheral_role_supported` provienen del adaptador predeterminado.

Si aparece `adapter_status: winrt_dependency_missing`, comprobar que
PyWinRT esté instalado en **el mismo intérprete** que ejecuta `py`.
Si aparece `api_error`, no concluir que el equipo carece de BLE:
solo significa que la API no pudo consultarse.

Aunque todas las capacidades sean verdaderas, `idc_session_verified`,
`gatt_connection_tested` y `verified_identity` continuarán siendo
`false`: faltan el enlace real y el verificador autorizado por TSE/GET Group.

El diagnóstico anterior `--bluetooth-check` y las lecturas de cédulas
físicas **siguen funcionando sin PyWinRT**.

## Prueba presencial y consentida del enlace BLE (experimental)

Esta prueba **no es un lector IDC**, no verifica identidad ni recupera atributos.
Solo intenta localizar el **servicio específico anunciado por el QR** y abrir
brevemente una conexión BLE, que se cierra automáticamente. No enumera nombres,
MAC, servicios ajenos ni características GATT. No almacena el QR ni el UUID.

Instalar **solo en una computadora de laboratorio**, no en producción:

```powershell
py -m pip install -r requirements-idc-ble-lab.txt
```

Cerrar la aplicación principal DMS, activar Bluetooth en Windows y tener la
aplicación IDC oficial abierta con el QR dinámico de una persona que **haya
autorizado expresamente la prueba**.

```powershell
py -m tools.idc_diagnostic --ble-link-check --port COM3 --consent
```

Sustituir `COM3` por el puerto real. La herramienta usa únicamente la
modalidad COM para evitar que un escáner HID imprima el QR en la terminal.
El QR se procesa en memoria y no se escribe en archivos o terminal.

Interpretaciones principales:

- `link_opened_then_closed`: conexión BLE breve exitosa, **no** sesión mdoc.
- `service_not_found`: no se vio el UUID anunciado durante la ventana de
  escaneo; puede deberse a que el teléfono no anunció aún el servicio,
  restricciones de Windows o que el flujo utiliza otro modo BLE.
- `phone_central_mode_only`: el QR requiere que el verificador actúe como
  periférico; esta prueba no implementa ese modo.
- `missing_peripheral_uuid`: falta el UUID esperado para este modo.
- `bleak_not_installed` / `cbor2_not_installed`: falta paquete opcional.
- `bluetooth_connection_error`: enlace fallido sin imprimir datos del móvil.

En todos los casos `verified_identity=false`,
`mdoc_session_established=false` e `idc_verification_available=false`.
La integración con SDK autorizado por TSE/GET Group sigue siendo necesaria.

**Alcance y privacidad:** la búsqueda BLE se limita al identificador de servicio
obtenido del QR presentado por el titular; no se guardan identificadores ni
resultados de otros dispositivos. Compartir solo el JSON técnico del resultado.

## Cuando se recibe `service_not_found`

`service_not_found` significa que en la ventana de escaneo no llegó un anuncio
con el UUID temporal del QR. **No es prueba de fallo del radio ni de identidad
inválida**. El QR puede anunciar un servicio que todavía no esté transmitiéndose.

Realizar un intento controlado de laboratorio:

1. Cerrar la aplicación principal que usa el puerto COM y dejar Bluetooth
   encendido y autorizado en ambos dispositivos.
2. Abrir en el teléfono la presentación de la IDC y generar un **QR vigente**,
   con el teléfono desbloqueado y la aplicación en primer plano.
3. Colocar el teléfono cerca del adaptador y ejecutar con el puerto real:

```powershell
py -m tools.idc_diagnostic --ble-link-check --port COMx --consent --ble-scan-seconds 30
```

No aumentar `--timeout` pensando que alarga el escaneo BLE: ese parámetro
controla la **captura serial**, no la búsqueda Bluetooth. La ventana BLE se
modifica exclusivamente mediante `--ble-scan-seconds` (3–30 segundos).

Si vuelve a aparecer `service_not_found`, efectuar por separado una prueba
con la **aplicación Verificador IDC oficial** en otro equipo compatible y con
consentimiento. El éxito de la aplicación oficial puede ayudar a distinguir
un problema de publicidad del teléfono de uno de interoperabilidad en Windows;
**no autoriza extraer datos de la aplicación oficial**.

**No** activar escaneos abiertos de todos los dispositivos, no publicar UUID,
direcciones MAC ni el QR, y no emparejar manualmente el teléfono desde la
configuración Bluetooth como sustituto de la negociación mdoc. Si el
transporte sigue sin aparecer, la siguiente etapa requiere revisar el
comportamiento real de la aplicación IDC y obtener el SDK autorizado.

## Decisión tras dos resultados `service_not_found`

El 20 de noviembre de 2026 se repitió la búsqueda dirigida de QR `mdoc:`
con periférico BLE anunciado y servicio UUID presente, tanto con la ventana
original como con ventana ampliada a 30 segundos: **no se encontró el servicio**.
Windows declaró BLE LE + roles central/periférico compatibles. El fallo sigue
sin causa demostrada.

**No continuar elevando el timeout ni cambiar de hardware por ahora.**
El TSE informa que el Verificador IDC oficial es gratuito para Windows,
iOS y Android, y que el instalador Windows debe solicitarse a
`Comercializacion@tse.go.cr` o al `2287-5885`:
https://www.tse.go.cr/idc/

La próxima prueba es comparar el funcionamiento del verificador oficial
en un entorno autorizado. Registrar únicamente resultados cualitativos:
**éxito/fallo, modo utilizado, offline/online, autorización solicitada**,
sin fotografiar pantallas ni registrar QR, UUID o datos de la persona.
Ver `docs/IDC_OFFLINE_BLE_READINESS.md`.

## Base criptográfica ISO/IEC 18013-5 — etapa qa10

Se agregó una preparación **local** de sesión mDoc para ensayar la estructura de
seguridad del protocolo sin conectarse por Bluetooth ni exponer atributos:

- Reconoce DeviceEngagement en forma de arreglo ISO 18013-5 y mapa candidato
  (posible perfil ampliado; **no se presume conformidad del TSE**).
- Exige cipher suite 1 y EDeviceKey tipo COSE EC2 sobre P-256, dentro de tag CBOR 24.
- Genera clave efímera EReaderKey, arma SessionTranscript QR y deriva
  **SKReader y SKDevice** mediante ECDH P-256 y HKDF SHA-256.
- Construye DeviceRequest sintético con `docType` y `nameSpaces` suministrados
  expresamente; no inventa los atributos ni el docType del TSE.
- Nunca imprime llaves, UUID, transcript, QR, cédula, nombres ni certificados.

En computadora de laboratorio, usando código de esta rama:

```powershell
py -m pip install -r requirements-idc-ble-lab.txt
py -m pip install "cryptography==46.0.4"
py -m tools.idc_diagnostic --mdoc-preflight --port COMx --consent
```

Usar el puerto COM real y el QR vigente del titular que haya autorizado la
prueba. El reporte solo contiene estados booleanos y códigos categóricos.
`local_crypto_preflight_passed_not_verified` demuestra **solo derivación
local de claves**. No demuestra sesión BLE, emisor legítimo ni identidad.

**La verificación completa sigue bloqueada** hasta integrar el transporte
GATT, recibir `DeviceResponse`, validar `IssuerAuth`/firma COSE,
certificados IACA de confianza, MSO/digests, DeviceAuth sobre la misma sesión
y la vigencia. Hasta entonces, NO rellenar el formulario de visitantes.

### Cifrado del mensaje de sesión (sintético, no conectado)

El núcleo incorpora `SessionCipherState` con AES-256-GCM, nonce de 12 bytes
(identificador de dirección de 8 bytes y contador big-endian de 4 bytes),
contadores independientes por dirección y rechazo de mensajes alterados o
reproducidos. Puede ensamblar una estructura `SessionEstablishment` con
`eReaderKey` y `data` cifrados para pruebas sintéticas **en memoria**.

No transmite aún la estructura al teléfono y no verifica un `DeviceResponse`.
Un mensaje descifrado NO equivale a una identidad autenticada: faltan
`IssuerAuth`, MSO, certificados y la vinculación `DeviceAuth`.

## Diagnóstico opcional de publicidad BLE — tras dos `service_not_found`

Un resultado `service_not_found` indica que el filtro por UUID del QR no
recibió el servicio anunciado, pero no permite distinguir si Windows recibe
anuncios BLE de otros equipos.

Esta opción **realiza un escaneo temporal más amplio** (sin filtro de UUID)
para observar publicidad BLE cercana, pero procesa los anuncios en memoria
y nunca registra dispositivos, nombres, direcciones, UUID ajenos ni paquetes.
**Requiere autorización adicional** (`--nearby-scan-ok`) además del
consentimiento de la persona que presenta la IDC.

Con el lector de DMS cerrado, Bluetooth habilitado en Windows, el teléfono
desbloqueado y la IDC mostrando un QR nuevo:

```powershell
py -m tools.idc_diagnostic --ble-observe-check --port COM5 --consent --nearby-scan-ok --ble-scan-seconds 20
```

Requiere `bleak`, `cbor2` y `pyserial` (ya usados en las pruebas previas).
No ejecuta emparejamiento, conexiones, lecturas GATT ni acceso a atributos.

Interpretación sin suposiciones:
- `target_service_advertised`: se observó el UUID del QR en anuncios BLE
  sin filtro; el filtro de la etapa anterior o sus tiempos pueden explicar la falla.
- `target_uuid_in_service_data_only`: el UUID aparece solo en service data;
  se debe revisar el método de publicidad del teléfono.
- `other_advertisements_seen_not_target`: hay anuncios BLE cercanos,
  pero no se vio el UUID de este QR; **no confirma que el teléfono haya sido observado**.
- `no_ble_advertisements_received`: la API no entregó anuncios BLE,
  sin que pueda concluirse por sí solo una falla física.
- `ble_scan_error`: el sistema no completó la observación.

Compartir únicamente el JSON. No compartir la imagen ni el QR `mdoc:`.
Conservamos las lecturas físicas y ningún documento IDC puede aceptarse.

## Error `bleak_not_installed` con Bleak ya instalado (bloqueo de WinRT)

En Windows 11/Python 3.13, un caso real mostró Bleak 3.1.0, CBOR2 y todas
sus dependencias WinRT instaladas. Sin embargo, la carga de
`winrt.runtime._winrt` falló con:

`ImportError: DLL load failed ... Una directiva de Control de aplicaciones bloqueó este archivo.`

Esto **no significa que falte instalar Bleak**: Windows bloqueó una extensión
nativa `.pyd` bajo una política de aplicación. El informe anterior era
ambiguo; ahora diferencia `windows_application_control_blocked` de
`ble_dependency_missing` y `ble_native_extension_load_error`.

Antes de presentar un QR, ejecutar:

```powershell
py -m tools.idc_diagnostic --ble-runtime-check
```

Esta instrucción **no escanea dispositivos ni abre un puerto COM**.
Si indica `windows_application_control_blocked`, consultar registros
`Microsoft-Windows-CodeIntegrity/Operational` (3077/3089) o
`Microsoft-Windows-AppLocker/EXE and DLL` (8004), y pedir al administrador
que revise la política y autorice formalmente componentes legítimos si
corresponde. Ver documentación de Microsoft:

- https://learn.microsoft.com/windows/security/application-security/application-control/app-control-for-business/operations/appcontrol-debugging-and-troubleshooting
- https://learn.microsoft.com/windows/security/application-security/application-control/app-control-for-business/applocker/using-event-viewer-with-applocker

No desactivar Smart App Control, WDAC, AppLocker ni mecanismos de integridad
como alternativa rápida. Una actualización de pip no modifica estas políticas.
El diagnóstico de formato/criptografía local puede continuar aunque la
prueba BLE esté bloqueada.

## Descubrimiento GATT de solo metadatos (tras enlace BLE confirmado)

Con `--ble-link-check` se consiguió `link_opened_then_closed` en Windows,
utilizando el servicio UUID efímero del QR. Se corrigió un indicador antiguo:
**ese enlace por sí solo NO comprueba características GATT**. Por eso
`gatt_link_tested=false` en la prueba de enlace a partir de esta etapa.

Para inspeccionar las características del servicio mDoc SIN leer valores,
suscribirse ni escribir datos, con la aplicación principal cerrada, Bluetooth
activo y un QR actualizado mostrado por el titular que consiente:

```cmd
py -m tools.idc_diagnostic --ble-gatt-check --port COM5 --consent --ble-scan-seconds 30
```

La herramienta solo abre una conexión dirigida al servicio BLE del QR,
inspecciona UUID y propiedades de las características `State`,
`Client2Server` y `Server2Client`, y cierra el enlace. Nunca imprime UUID,
nombres, direcciones ni valores. Resultado `gatt_profile_discovered_not_session_started`
significa **solo que el perfil GATT básico está presente**, NO que se
haya establecido una sesión mDoc ni verificado la IDC.

Resultados posibles:
- `gatt_profile_discovered_not_session_started`: perfil y propiedades
  básicos presentes, siguiente paso es intercambio mDoc cifrado
- `gatt_profile_incomplete_or_different`: características o permisos
  distintos a los que esperamos; compartir los flags del JSON
- `service_not_found`: QR obsoleto, publicidad BLE temporal ausente,
  o servicio no detectado en la ventana de escaneo
- `gatt_discovery_error`: error técnico al descubrir propiedades;
  no se exponen excepciones ni datos del dispositivo

El escaneo y la inspección de GATT no proporcionan información personal
ni validan credenciales.

## Etapa qa11 — señalización State BLE con consentimiento reforzado

La última prueba de campo confirmó `gatt_profile_discovered_not_session_started`
con `State`, `Client2Server` y `Server2Client` presentes y propiedades válidas.

Siguiente prueba **activa pero limitada**: el lector se conecta al UUID
efímero extraído del QR, se suscribe a las notificaciones `State` y
`Server2Client`, envía `State=Start (0x01)`, observa brevemente cualquier
notificación de estado **sin almacenar contenido**, envía `State=End (0x02)`,
anula las suscripciones y desconecta. Nunca transmite un `DeviceRequest`,
ni escribe en `Client2Server`, ni reensambla respuestas del teléfono.

Esto requiere dos permisos explícitos: `--consent` (titular presente) y
`--allow-gatt-write` (permiso para enviar señales de sesión GATT). La
operación puede hacer que el teléfono cierre o reinicie la presentación
IDC; para otra prueba debe generarse un QR nuevo.

```cmd
py -m tools.idc_diagnostic --ble-state-check --port COM5 --consent --allow-gatt-write --ble-scan-seconds 30
```

`state_start_and_end_sent_no_document_request` significa **solo**
que ambos bytes de control se enviaron desde Windows; no prueba que el
teléfono los procesara, que la sesión mDoc se estableciera o que la
identidad fuese auténtica. `peer_end_observed` registra únicamente
si el teléfono notificó el byte `End`. Los reportes no incluyen QR,
nombres, UUID, MAC, certificados, ni contenido GATT.

Para llegar a una verificación de identidad faltan el envío de
`SessionEstablishment` con una solicitud de atributos explícitamente
autorizada, recepción de `SessionData`, validación de `IssuerAuth`,
todos los digests, `DeviceAuth` y confianza del emisor.

## Etapa qa11 — transporte BLE cifrado con solicitud de documento inexistente

La prueba de campo del 26 de noviembre confirmó el envío de State Start/End y
ambas suscripciones BLE. Este siguiente paso **sí transmite un mensaje cifrado**
`SessionEstablishment` fragmentado al canal `Client2Server`, pero su
`DeviceRequest` está fijado EN EL CÓDIGO a un `docType` y un elemento
`org.example` deliberadamente inexistentes. No se aceptan nombres de
documentos ni campos reales por línea de comandos, y la prueba nunca registra
visitantes.

El teléfono normalmente rechazará o ignorará esa solicitud sintética. Que no
responda NO es evidencia de incompatibilidad de la IDC. Si responde con
`SessionData`, el programa puede probar la autenticación AES-GCM en memoria,
pero **no decodifica atributos de identidad ni publica el contenido**. Una
respuesta criptográficamente autenticada NO acredita el emisor ni identidad.

Solo en equipo de laboratorio, con titular presente y permiso para generar
un intercambio mDoc cifrado experimental:

```cmd
py -m tools.idc_diagnostic --ble-session-lab --port COM5 --consent --allow-synthetic-exchange --ble-scan-seconds 30
```

Recomendaciones: cerrar app principal, activar Bluetooth, mantener IDC abierta
con QR NUEVO, y prever que el teléfono cierre o rechace la sesión. Evitar
pruebas repetidas innecesarias. El modo usa tamaño de trama conservador
(ATT MTU 23 / 20 bytes por escritura) y desacelera entre fragmentos.

Posibles estados:
- `encrypted_reply_authenticated_not_identity`: hubo SessionData AES-GCM
  autenticado; **no hay verificación de firma, DeviceAuth o certificado IACA**
- `no_response_to_synthetic_document_request`: el teléfono no respondió;
  resulta compatible con rechazo del tipo de documento ficticio
- `holder_ended_session_after_synthetic_request`: el teléfono terminó
  el intercambio sin revelar datos
- `encrypted_request_not_fully_sent`, `ble_exchange_error`: fallo de
  envío/transporte; compartir únicamente JSON sanitizado

**No utilizar** este modo para solicitar identidad real. Requerimos conocer
docType/namespaces exactos del perfil IDC, permisos del titular y raíz IACA
confiable antes de habilitar el flujo de verificación.

## Etapa qa12 — categorías de DeviceResponse cifrado autenticado

La primera sesión real de laboratorio ya produjo:
`encrypted_reply_authenticated=true`,
`device_response_cbor_present=true`, y
`status=encrypted_reply_authenticated_not_identity`.

Para distinguir respuestas vacías, documentos inexistentes y errores sin
exponer datos personales, ahora se incluyen indicadores adicionales,
extraídos **solo después** de validar AES-GCM:

- `response_status_code`: código numérico pequeño del `DeviceResponse`
  (o `null` cuando no existe); `0` suele indicar procesamiento correcto,
  **no verificación de identidad**.
- `response_status_category`: `ok`, `nonzero`, `invalid_or_missing`,
  `unavailable`.
- `response_document_count_category`: `absent`, `none`, `one`,
  `multiple`, `invalid`, `unavailable`. Nunca enumera documentos.
- `response_document_errors_present`: si existe una estructura no vacía
  de errores por documento; nunca publica docType ni códigos detallados.
- `response_unexpected_document_present`: se obtuvo algún documento
  pese a que la solicitud era de un tipo **ficticio**. No extraer contenido.
- `session_data_field_present`: existencia de un campo `data` binario
  en `SessionData`; independiente de estado de la sesión.

Se mantiene el docType de prueba fijo, no configurable por CLI, y todas las
banderas de verificación de identidad siguen en `false`.

```cmd
py -m tools.idc_diagnostic --ble-session-lab --port COM5 --consent --allow-synthetic-exchange --ble-scan-seconds 30
```

El titular debe autorizar la nueva solicitud experimental y generar un
QR nuevo. Compartir exclusivamente el JSON categórico. No conservar el
contenido de la respuesta o el QR.
