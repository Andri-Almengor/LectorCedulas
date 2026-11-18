# IDC - plan de integración por versiones

## Supuestos verificados y pendientes

- Verificación IDC offline: contemplada por el TSE mediante su aplicativo oficial.
- Un QR `mdoc:` por sí mismo NO prueba una identidad ni los datos del titular.
- Primera captura: `mdoc:` + Base64URL válido (220 bytes), primer tipo CBOR `map`.
- Estructura CBOR completa, perfil oficial del TSE y transporte real: pendientes de diagnóstico ampliado y validación autorizada.
- BLE/NFC, certificados de confianza, SDK oficial Windows y permisos de integración:
  pendientes de confirmación oficial.
- No se ha adquirido ni integrado ningún SDK del TSE/GET Group.
- No se promete costo cero del SDK; tampoco tiempos definitivos.
- Nunca tratar una URL extraída de un mDoc como comprobante de identidad.

## Versionado

**4.0.0-qa8: respaldo fijo.** Lectura de documentos físicos y QR URL actuales.

**4.0.0-qa9: presente PR.**
- Diagnóstico local independiente COM/HID, sin capturar ni guardar QR bruto.
- Identificación limitada de formato `mdoc:`; sin decodificar atributos.
- Bloqueo explícito de mDoc no verificado dentro del parser principal.
- Preservación de formatos físicos y de la consulta URL TSE existente.

**4.0.0-qa10: posterior a muestra y acuerdo de SDK.**
- Verificador offline autorizado en componente independiente, con política fail-closed.
- Validación de firma, emisor, sesión, vigencia y reglas de datos consentidos.
- Pruebas con documentos sintéticos, negativos y reproducción de sesiones.
- Compatibilidad con lector físico y BLE/NFC según el flujo real.

**4.0.0-rc1: piloto MICITT.**
- Pruebas físicas en Windows y Lenel, regresión de cédulas, instalación controlada.
- Aprobación de seguridad y privacidad; plan de reversión a qa8.
- Sin fusionar ni desplegar hasta completar la matriz de pruebas.

## Controles obligatorios

1. El lector original debe continuar pudiendo leer barras, QR URL y CSV/XOR.
2. Sin verificación criptográfica completa no se escribe ninguna identidad IDC en formularios.
3. No transmitir ni conservar QR dinámicos, certificados privados ni datos personales
   en logs, archivos de prueba, PRs o telemetría.
4. El resultado del SDK debe asignarse al documento y sesión correctos.
5. Verificación local no equivale a consulta registral actualizada ni prueba de revocación online.
6. Probar BLE, Windows, lectores COM/HID y permiso institucional antes de prometer hardware.
7. La instalación final y su rollback requieren copia de configuración/licencia del cliente.
