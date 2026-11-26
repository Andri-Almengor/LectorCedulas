# QA15 — preparación de perfil IDC y consumo único
Base: PR #39 (35 pruebas confirmadas en Windows).

## Cambios
- Una instancia de SyntheticReaderAttempt crea un transcript de laboratorio
  nuevo y lo consume una única vez, incluso si falla la verificación. Protege
  contra dos llamadas concurrentes sobre la misma instancia. No es un registro
  persistente de replay ni modifica el transporte BLE.
- inspect_profile_readiness valida un perfil local mínimo, rechaza duplicados,
  marcadores de ejemplo y política ReaderAuth desconocida. Comprueba la
  coincidencia SHA-256 de un certificado candidato con una huella obtenida
  independientemente, y la forma CA/autofirma EC. No acredita confianza,
  vigencia, revocación o autenticidad del perfil.
- No se solicita un documento real ni se añade un perfil TSE inventado.
  No cambia la aplicación principal.

## Información necesaria para la próxima etapa
1. Tipo de documento exacto y namespace(s) de la IDC.
2. Nombres exactos de atributos mínimos (nombre y número de identificación).
   El modelo provisional QA15 admite un namespace y un campo de nombre;
   ampliar según la documentación real (p. ej. nombres/apellidos separados).
3. Política de ReaderAuth y credenciales de lector si fueran necesarias.
4. Certificado(s) públicos de confianza y huella por un canal autenticado
   independiente; política de actualización, vigencia y revocación.
5. Vector de prueba autorizado sin datos personales reales.

La libertad de implementar un lector no proporciona automáticamente estas
especificaciones. Nunca utilizar una raíz enviada por el documento como ancla
sin comprobar su procedencia. No adivinar identificadores ni habilitar
registro automático hasta completar verificación.

## Pruebas
```cmd
py -m pytest tests/unit/test_idc_issuer_auth.py tests/unit/test_idc_signed_items_lab.py tests/unit/test_idc_device_auth_lab.py tests/unit/test_idc_profile_readiness.py -q
```
Esperadas: 51 (35 anteriores + 16 nuevas). No requiere COM5 ni teléfono.
