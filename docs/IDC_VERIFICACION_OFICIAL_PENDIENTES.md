# IDC Costa Rica — requisitos antes de pasar a verificación real

**Estado al 26 de noviembre de 2026**: el laboratorio con lector COM5
conectó a la IDC por BLE, verificó GATT State/Client2Server/Server2Client,
envió un `SessionEstablishment` con petición de docType ficticio, recibió
`SessionData` y autenticó con éxito AES-GCM. La aplicación del teléfono
respondió `DeviceResponse.status=0`, SIN `documents` y CON
`documentErrors`, coherente con la petición ficticia.

**Esto no autentica ninguna identidad**. Nunca activar el registro de
visitantes con una IDC a partir de estos estados.

## Insumos oficiales necesarios

1. **Esquema de la credencial IDC**: `docType`, namespaces y nombres
   exactos de atributos autorizados, con sus tipos CBOR. Definir solicitud
   estrictamente mínima y consentimiento del titular; confirmar si
   `ReaderAuth` o algún certificado/registro del verificador es requerido.
2. **Anclas de confianza**: certificado(s) del emisor pertinentes, cadena
   Document Signer/Issuer (IACA u otra arquitectura oficial), política de
   certificación, vigencias, cambios de claves y revocación. Verificar
   procedencia de esos certificados por un canal auténtico del TSE.
3. **Reglas de autenticación**: COSE_Sign1 de `IssuerAuth`, MSO
   (`docType`, `validityInfo`, `valueDigests` y vínculo a certificados),
   `DeviceAuth` sobre SessionTranscript y políticas de autenticación del
   titular. Tratar ausencias, caducidad, sustitución, alteraciones y replays
   como rechazos.
4. **Restricciones funcionales y privacidad**: confirmar qué atributos
   pueden presentarse fuera de línea y cómo se gestionan, retienen o
   descartan. Nunca almacenar material biométrico ni fotografías como parte
   del diagnóstico. El TSE publica sus términos sobre verificación offline
   por QR, BLE/NFC y tratamiento de datos personales.
5. **Interoperabilidad**: obtener el verificador oficial IDC para Windows
   en el laboratorio y comparar, con el mismo documento de prueba autorizado,
   su resultado (sin extraer secretos ni descompilar el software). Pedir al
   TSE documentación o SDK de integración formal, si existe.

## Canal oficial verificado

El sitio oficial del TSE indica que el **Verificador IDC para Windows**
se puede solicitar al **Departamento de Comercialización de Servicios**:

- Correo: `Comercializacion@tse.go.cr`
- Teléfono: `2287-5885`
- Fuente: https://www.tse.go.cr/idc/
- Términos: https://www.tse.go.cr/pdf/IDC/terminosycondiciones.html

### Texto breve para enviar

Asunto: Consulta técnica de integración IDC offline (Windows / ISO 18013-5)

> Somos desarrolladores de un sistema de registro de visitas en Windows
> y necesitamos integrar de forma segura la verificación offline de la
> Identidad Digital Costarricense. Nuestro laboratorio ha comprobado el
> transporte BLE mDoc y la autenticación AES-GCM de respuestas a una
> petición sintética, sin tratar datos de identidad reales.
>
> Solicitamos información sobre el perfil oficial de interoperabilidad
> (`docType`, namespaces y atributos autorizados), requisitos de
> `ReaderAuth`, certificados raíz o mecanismo oficial de confianza del
> emisor y su actualización/revocación, y si existe SDK/API o documentación
> para integrar el verificador IDC en un sistema propio. También queremos
> solicitar el Verificador IDC oficial para Windows para pruebas
> controladas.
>
> Agradecemos nos indiquen el procedimiento formal o departamento
> técnico correspondiente.

## Política de aceptación

El programa NO puede declarar una IDC válida por el mero hecho de que:
- el QR se lea
- BLE/GATT establezca conexión
- las claves ECDH/HKDF se deriven localmente
- `SessionData` sea autenticado por AES-GCM
- `DeviceResponse.status=0` indique éxito general
- `response_structure_acceptable=true` indique CBOR bien formado

Solo se podrá activar integración de identidad tras implementar y
ensayar con vectores oficiales validaciones exhaustivas de credenciales,
mecanismos de confianza y autorización de atributos. `main` no se toca
en estas ramas experimentales.
