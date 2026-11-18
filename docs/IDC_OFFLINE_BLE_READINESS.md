# IDC — preparación para una prueba BLE offline en Windows

## Alcance

Este documento **no** verifica una IDC ni requiere capturar nuevos datos
personales. La lectura real del QR ya anunció BLE y NFC. El siguiente
objetivo es comprobar qué puede hacer la computadora del punto de registro.

## Paso 1 — Inspección local del hardware

En **Administrador de dispositivos** comprobar si existe la categoría
**Bluetooth**, si el adaptador está habilitado y si Windows muestra
errores de controlador. No confundir un lector QR USB con un radio BLE.

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
