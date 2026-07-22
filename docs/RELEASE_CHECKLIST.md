# Checklist de liberación

## Código y automatización

- [x] Rama aislada desde commit requerido.
- [x] Sin merge automático.
- [x] Runtime sin monkey patches por importación.
- [x] 56 pruebas automatizadas aprobadas; 2 pruebas condicionadas fueron omitidas en entorno aislado.
- [x] Dependencias fijadas y workflow Windows/Linux.
- [x] JSON crítico atómico con backup.
- [x] Licencias y manifests Ed25519.
- [x] Logs redactados.
- [ ] GitHub Actions verde en la rama.
- [ ] Ruff verde en Windows y Linux.

## Build

- [x] ejecutable principal nombrado `LectorCedulasDMS.exe`.
- [x] updater compilado como `DMSUpdater.exe`.
- [x] `--noconfirm --clean`.
- [x] versión única `4.0.0-qa1`.
- [x] SBOM obligatorio en builder.
- [x] Inno diferencia error 110.
- [ ] Build ejecutado en Windows limpio.
- [ ] Comparación de dos builds reproducibles.
- [ ] Firma Authenticode de EXE y Setup.

## Pruebas físicas obligatorias

- [ ] Primera lectura después de iniciar: 100/100.
- [ ] Primera lectura tras cambio de configuración: 100/100.
- [ ] Configuración de un campo: 100/100.
- [ ] Configuración mult campo: 500/500.
- [ ] Cero escritura en app equivocada.
- [ ] Cero pérdida en estrés.
- [ ] Desconexión/reconexión USB.
- [ ] Lenel OnGuard local.
- [ ] Navegadores y apps Windows.
- [ ] RDP.
- [ ] Antivirus activo.
- [ ] Escalado 100–200 % y multimonitor.
- [ ] Suspensión/reanudación/cambio usuario.

## Update/rollback

- [ ] instalación limpia.
- [ ] actualización sobre versión anterior.
- [ ] licencia/config/favoritos/COM preservados.
- [ ] manifest alterado rechazado.
- [ ] downgrade rechazado.
- [ ] archivo bloqueado reportado.
- [ ] rollback comprobado.
- [ ] reparación y desinstalación.

## Decisión

**No liberar como estable** mientras exista cualquier P0/P1 abierto o falte la matriz física. La etiqueta actual es `4.0.0-qa1`.
