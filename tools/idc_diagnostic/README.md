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

Ejecutar nuevamente el mismo comando con la rama actualizada del PR #22.
El informe incluirá `cbor_structure_decoded`, `cbor_profile_hint`,
`known_engagement_fields_present` y `transport_candidates`.
El perfil es solo una hipótesis estructural; el SDK autorizado debe realizar
la autenticación criptográfica antes de obtener datos de una persona.
