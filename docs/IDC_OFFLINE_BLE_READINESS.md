# IDC — preparación para una prueba BLE offline en Windows

## Alcance

Este documento **no** verifica una IDC ni requiere capturar nuevos datos
personales. La lectura real del QR ya anunció BLE y NFC. El siguiente
objetivo es comprobar qué puede hacer la computadora del punto de registro.

## Paso 1 — Inspección local del hardware

En **Administrador de dispositivos** comprobar si existe la categoría
**Bluetooth**, si el adaptador está habilitado y si Windows muestra
errores de controlador. No confundir un lector QR USB con un radio BLE.

O usar la herramienta de diagnóstico agregada al repositorio:

```powershell
py -m tools.idc_diagnostic --bluetooth-check
```

No realiza emparejamiento ni búsqueda de dispositivos. Devuelve `detected`
si Windows enumera al menos un dispositivo de la clase Bluetooth con estado
OK. Un resultado `detected` **no demuestra que exista un radio BLE apto para
ISO 23220**, que esté disponible el perfil correcto ni que funcione
la sesión de IDC. `unknown` no debe interpretarse como ausencia física.

Alternativamente, desde PowerShell local:

```powershell
Get-PnpDevice -Class Bluetooth | Select-Object Status, Class
```

El comando omite nombres de personas y direcciones de dispositivos. Tener
la clase Bluetooth operativa es solo un indicador preliminar;
**no acredita soporte BLE central, la compatibilidad GATT ni ISO 23220**.

Si no aparece la categoría, revisar si el equipo cuenta con adaptador
Bluetooth, si está inhabilitado o si falta el controlador. No comprar
hardware antes de verificar la necesidad y el SDK final.

## Paso 2 — Verificar condiciones de prueba

- Windows actualizado, permisos de Bluetooth y radio encendida.
- Lector QR ya probado y capaz de captar íntegros 299 bytes de contenido.
- Una IDC real, con autorización de su titular, y el verificador oficial
  disponible para verificar por la vía autorizada.
- No utilizar programas de captura de paquetes o barridos BLE indiscriminados.
- No mostrar ni almacenar direcciones MAC, nombres de dispositivos próximos,
  QR íntegros, claves, tokens ni atributos de identidad.
- Confirmar disponibilidad de certificados de confianza y restricciones
  de uso de software del TSE/GET Group.

## Paso 3 — Probar el transporte mediante SDK autorizado

Solo cuando exista un SDK o interfaz oficial compatible:

1. Iniciar sesión de verificación con QR dinámico vigente.
2. Establecer canal BLE según parámetros del engagement y autorización.
3. Verificar firma del emisor, autenticación de sesión, integridad, vigencia
   y política de confianza sin exponer atributos no consentidos.
4. Medir si el proceso funciona sin conexión externa y si requiere renovación
   periódica de material de confianza.
5. Rechazar sesiones incompletas, reutilizadas, inválidas y errores de enlace.
6. Solo entonces habilitar el llenado del formulario de visitas.

## Qué informar a DMS en esta fase

Indicar únicamente si la computadora muestra adaptador Bluetooth operativo,
la versión general de Windows, y si la institución permite usar BLE en el puesto.

No remitir identificadores de radio, capturas de IDC, PII ni archivos de sesión.

## Nota sobre NFC

El QR anuncia NFC además de BLE, pero el lector de QR existente no es un
lector NFC. No asumir NFC disponible sin lector, controlador y compatibilidad
del SDK. BLE es primera alternativa de investigación, no garantía de éxito.

## Riesgos y reversión

La verificación offline no constituye una consulta registral en línea actualizada
al instante. Reglas de revocación/caducidad y confianza local deben definirse
antes de producción. El respaldo `backup/pre-idc-4.0.0-qa8-2026-11-18`
permanece disponible para recuperar el código original, mientras que los
archivos y licencias instalados localmente exigen respaldo adicional.

## Estrategia para instalaciones sin Bluetooth

**Funcionalidades que deben seguir disponibles**
- Código de barras y QR de cédulas físicas mediante lector COM/HID actual.
- Registro de visitantes mediante los flujos existentes.
- Si la IDC no puede verificarse por el nuevo componente, no completar
  automáticamente identidad desde `mdoc:` o una URL parcial.

**Alternativas IDC**
1. Verificación con el aplicativo oficial en un equipo institucional compatible
   y registro manual de datos autorizados en el sistema de visitantes.
2. Evaluar adaptador USB BLE compatible, solo si el SDK exige BLE y funciona
   con el sistema operativo y controladores instalados.
3. Evaluar NFC solo cuando existan lector NFC, software y autorizaciones
   que lo soporten; el lector QR tradicional no funciona como lector NFC.

Para la futura interfaz: aislar módulo IDC del resto de parsers.
Si no se detecta radio o falla el motor de verificación, mostrar un estado
de `IDC no disponible en este equipo` y conservar las demás lecturas.
Nunca registrar una IDC como autenticada sin prueba criptográfica.

## Paso adicional — API WinRT de capacidades BLE

La salida `bluetooth_class_status: detected` fue confirmada en una
computadora de pruebas de DMS el 20 de noviembre de 2026. **No acredita BLE**.

Para consultar propiedades del adaptador predeterminado sin escanear equipos
de terceros, desde la rama del diagnóstico WinRT ejecutar:

```powershell
py -m pip install "winrt-Windows.Devices.Bluetooth==4!10.0.28000.2957"
py -m tools.idc_diagnostic --ble-capabilities
```

Interpretación:

- `low_energy_supported=true`: el adaptador declara Bluetooth LE.
- `central_role_supported=true`: el adaptador declara rol central BLE.
- `peripheral_role_supported=true`: declara rol periférico BLE.
- `adapter_status=winrt_dependency_missing`: falta módulo opcional.
- `adapter_status=no_default_adapter`: la API no encontró adaptador.
- `adapter_status=api_error`: fallo consultando Windows; NO equivale
  a incompatibilidad física.

El QR observado anuncia BLE/NFC, pero el rol exacto de la sesión debe
deducirse de las opciones completas del engagement con un motor compatible.
Si el adaptador soporta rol central, solo se supera la prueba de hardware:
NO confirma que la IDC o el SDK establezcan sesión correctamente.
