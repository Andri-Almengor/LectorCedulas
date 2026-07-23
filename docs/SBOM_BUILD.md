# Generación de SBOM

El dashboard instala sus dependencias de construcción desde `requirements-build.txt`.

La dependencia `cyclonedx-bom` proporciona el comando `cyclonedx-py` utilizado por `tools/release_builder.py` para generar `sbom.cdx.json` dentro del instalador y de los paquetes de actualización.

## Ejecución recomendada en Windows

Ejecute `EJECUTAR_DASHBOARD.bat`. El script:

1. instala `requirements-build.txt` con el mismo intérprete `py`;
2. agrega al `PATH` la carpeta `Scripts` de ese intérprete;
3. inicia `dashboard.py`.

Para reparar manualmente un entorno existente:

```bat
py -m pip install "cyclonedx-bom==7.2.1"
```
