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
