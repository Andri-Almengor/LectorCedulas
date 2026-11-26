# Implementación de IssuerAuth — prevalidación ISO/IEC 18013-5

## Nuevo código: `tools/idc_diagnostic/issuer_auth.py`

El módulo implementa una **prevalidación parcial y desconectada** con fixtures
sintéticos y una raíz IACA confiable **proporcionada explícitamente**.

Se comprueba estructura COSE_Sign1, firma ES256, cadena X.509 de un solo salto
IACA → Document Signer, extensiones básicas, vigencia, docType del MSO y
ventana temporal de validez del documento. También hay una primitiva para
comparar hashes SHA-256 de elementos issuer-signed con su digest firmado.

No se utiliza el almacén global de certificados de Windows ni se confía en
certificados autoproclamados por el teléfono. **No se incorpora ningún
certificado supuesto del TSE**.

### Limitaciones intencionales

- Solo acepta ES256 y cadena directa de un único certificado de Document Signer.
- Aún no comprueba todos los digests de todos los namespaces ni el
  `DeviceAuth` vinculado al `SessionTranscript`.
- No hay validación de revocación (CRL/OCSP), VICAL ni políticas propias del TSE.
- No decodifica ni devuelve nombres, cédulas u otros atributos.
- El resultado de prevalidación exitosa nunca marca `verified_identity=true`;
  sigue prohibido llenar formularios desde una IDC.
- No hay lector BLE funcional: se mantiene el resultado de campo
  `service_not_found` y falta interoperabilidad con el teléfono.

### Pruebas

La CI genera en memoria certificados de laboratorio IACA y DS sobre P-256,
firma un MSO sintético y verifica tanto los casos válidos como manipulaciones
de firma, confianza, docType, vigencia y digest. No se utilizan documentos
de personas reales ni certificados oficiales no suministrados.
