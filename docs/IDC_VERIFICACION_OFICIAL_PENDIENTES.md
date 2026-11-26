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

## Evaluación de alternativas — 26/11/2026

### Decisión para DMS / LectorCedulas

**Continuar con la implementación Python/Bleak existente en el laboratorio.**
Las pruebas reales con COM5 confirmaron DeviceEngagement QR, servicio BLE
periférico, características GATT, State Start/End, intercambio
SessionEstablishment cifrado, autenticación AES-GCM de una respuesta y
`DeviceResponse` con error esperado ante un docType sintético. No comprar
otro hardware para el laboratorio ni migrar automáticamente a C# o Electron.

En el producto final, la verificación de documentos digitales se deberá
aislar como una interfaz de verificador que solo emita un resultado positivo
después de completar validación criptográfica y de confianza. Mantener
la ruta de cédulas físicas intacta y una alternativa autorizada con el
verificador oficial mientras el desarrollo propio no esté listo.

### Hardware

| Componente | Situación de laboratorio | Observaciones |
| --- | --- | --- |
| Escáner QR 2D | **Comprobado** en COM5 | Conservar la captura temporal del QR; nunca loguearlo |
| Bluetooth LE | **Comprobado** con WinRT/Bleak | GATT y respuesta cifrada autenticada en teléfono real |
| NFC USB | No requerido para el flujo QR + BLE | No comprar hasta justificar un segundo transporte |
| Cámara web | No necesaria en el flujo COM5 actual | Algunos SDK requieren cámara aunque el código existente no |

### Comparación de SDK (no confundir soporte ISO con interoperabilidad IDC)

| Alternativa | Hechos contrastados | Limitaciones para esta integración |
| --- | --- | --- |
| Python + Bleak, cbor2 y cryptography | Transporte QR/BLE y sesión cifrada probados en nuestro laboratorio | Falta confianza certificada del TSE, validación completa de IssuerAuth/MSO/digests/DeviceAuth/revocación y esquema de IDC |
| Scytáles `MdlIsoReaderDotNetSDK` | Paquete NuGet de lector ISO/IEC 18013-5 para Windows/.NET 8.0, BLE offline; requiere Visual Studio y el fabricante describe cámara + adaptador Bluetooth | Solicitar licencia y soporte; confirmar si admite QR por COM5, perfiles mDoc no-mDL, confianza IDC/TSE y API adecuada. No asumir compatibilidad Costa Rica ni soporte NFC offline |
| `stelauconseil/mdoc-web-verifier` | Código abierto Apache-2.0 para Web Bluetooth y verificación COSE/IssuerAuth, digests, DeviceAuth e importación de IACA/VICAL | Su lista raíz precargada NO contiene al TSE; no usar certificados de otras jurisdicciones. Auditar implementación, dependencias, políticas locales y almacenamiento de claves antes de reutilizar código |
| Verificador IDC oficial para Windows | El TSE confirma disponibilidad gratuita previa solicitud por Comercialización | Utilizar como referencia de interoperabilidad, confirmar posibilidad legal/técnica de integración; no presumir SDK/API |

Fuentes revisadas:
- TSE IDC oficial: https://www.tse.go.cr/idc/
- TSE términos: https://www.tse.go.cr/pdf/IDC/terminosycondiciones.html
- NuGet Scytáles: https://www.nuget.org/packages/MdlIsoReaderDotNetSDK/
- Documentación fabricante: https://www.scytales.com/sdk-documentation
- Verificador web abierto: https://github.com/stelauconseil/mdoc-web-verifier

**Precisión sobre certificados:** no identificar automáticamente la PKI
Nacional de Firma Digital con la autoridad IACA que firme una IDC. Un
verificador debe confiar en los certificados y políticas concretos que
el TSE confirme para el perfil IDC. No se ha confirmado un enlace público
oficial en estas fuentes con la raíz IACA de la IDC, ni el docType/namespace
concreto. No importar raíces arbitrarias ni inventar valores.

**Precisión sobre modalidades:** la documentación del TSE contempla
verificación sin conexión mediante QR/BLE/NFC y una modalidad de
verificación contra servicios institucionales; no inferir que ambos
ofrecen las mismas garantías, campos o acceso para SDK de terceros.

### Fecha regulatoria

En comunicado del **10/11/2026**, el TSE recordó que la IDC tendrá
aceptación obligatoria en instituciones públicas y privadas a partir del
**01/01/2027**. Planificar un procedimiento operativo compatible
mediante verificador oficial mientras los componentes de validación propia
continúen en laboratorio.

Fuente: https://tse.go.cr/comunicado1228.html

### Criterios de avance para PR de verificación real

- [ ] Obtener especificación oficial docType, namespaces, atributos, tipos CBOR y lector autorizado; registrar procedencia institucional
- [ ] Obtener raíces de confianza y procedimiento de rotación/revocación publicado por fuente oficial y confirmar IACA vs PKI de firma digital
- [ ] Implementar validación completa de cadena y política del emisor, IssuerAuth, MSO, todos los digests revelados, DeviceAuth y prevención de replay
- [ ] Definir captura de consentimiento y solicitud mínima necesaria para registro de visitas bajo Ley 8968
- [ ] Probar vectores válidos, alterados, vencidos, revocados y document types no coincidentes
- [ ] Comparar resultados con el Verificador IDC para Windows oficial, sin extraer secretos de terceros
- [ ] Integrar solamente un resultado explícito de identidad verificada; no permitir que `status=0` o `encrypted_reply_authenticated=true` autoricen visitas
- [ ] Ejecutar CI Windows y Linux, auditoría de dependencias y revisión de seguridad antes de fusionar a `main`
