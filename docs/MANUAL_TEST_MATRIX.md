# Matriz de pruebas manuales y físicas

Todos los resultados están inicialmente en `PENDIENTE`. No se debe cambiar a `PASÓ` sin evidencia real.

| ID | Caso | Precondiciones | Pasos resumidos | Resultado esperado | Resultado obtenido | Evidencia | Versión/equipo/fecha | Estado | Sev. si falla |
|---|---|---|---|---|---|---|---|---|---|
| M-001 | Lenel primer scan | Lenel abierto; config normal | iniciar app; enfocar primer campo; escanear 100 veces reiniciando | 100/100 completos | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-002 | Scan tras cambio rápido | dos favoritas | alternar; escanear inmediatamente, 100 veces | 100/100 usa nueva config | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-003 | Config un campo | campo específico | enfocar; 100 scans | solo campo designado | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-004 | Config mult campo | formulario 4+ campos | 500 scans controlados | cero vacíos/posición errónea | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-005 | Chrome | página HTML fixture | escribir y leer DOM | valores exactos | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-006 | Edge | página HTML fixture | igual M-005 | valores exactos | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-007 | Firefox | página HTML fixture | igual M-005 | valores exactos | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-008 | Bloc de notas | documento vacío | escribir un campo | texto exacto; clipboard restaurado | No ejecutado | pendiente | por completar | PENDIENTE | P2 |
| M-009 | Tkinter fixture | app test | mult campo | entradas exactas | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-010 | WinForms fixture | .NET disponible | mult campo y validación | entradas exactas | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-011 | WPF | fixture WPF | mult campo | entradas exactas/fallo seguro | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-012 | Dos Chrome | dos ventanas mismo PID | escanear A; activar B | cancela; no escribe B | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-013 | Form cerrado | scan y cerrar antes de escritura | esperar | cancela/notifica | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-014 | Form minimizado | scan y minimizar | observar | restaura target exacto o cancela | No ejecutado | pendiente | por completar | PENDIENTE | P2 |
| M-015 | Cambio de app | scan Lenel; activar navegador | observar | no escribe navegador | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-016 | Cola llena | writer pausado | enviar >64 frames sintéticos | rechazo visible, listener vivo | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-017 | 100 scans rápidos | fixture serial | ráfaga controlada | orden y cero pérdida aceptada | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-018 | Cancelación | escritura compatibilidad | Ctrl+Alt+Esc y bandeja | se detiene; teclas liberadas | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-019 | CPU alta/equipo lento | 90 % CPU | 100 scans | cero corrupción | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-020 | RDP | sesión remota | mult campo | exactitud o fallo explícito | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-021 | USB desconectado | lector activo | desconectar/reconectar | RECONNECTING→READY; siguiente scan funciona | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-022 | Suspensión | equipo portátil | suspender/reanudar | reconecta sin reinicio | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-023 | Cambio usuario | dos usuarios | cambiar sesión | no escribe en sesión equivocada | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-024 | Antivirus | Defender/EDR activo | build e instalar | error real reportado; 110 diferenciado | No ejecutado | pendiente | por completar | PENDIENTE | P2 |
| M-025 | Clipboard texto | copiar texto marcador | escanear | marcador restaurado | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-026 | Clipboard imagen | copiar imagen | escanear | imagen no alterada; Unicode correcto | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-027 | Usuario tecleando | iniciar scan y escribir | observar | cancela ante pérdida de foco; no mezcla | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-028 | Mouse esquina | fail-safe pyautogui | mover esquina durante scan | cancelación controlada, sin crash | No ejecutado | pendiente | por completar | PENDIENTE | P2 |
| M-029 | Escalado | 100/125/150/200 % | bandeja/configurador | UI usable | No ejecutado | pendiente | por completar | PENDIENTE | P3 |
| M-030 | Multimonitor | 2+ monitores | targets en ambos | HWND exacto correcto | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-031 | Tema/resolución | claro/oscuro, 1024x768 | abrir UIs | controles visibles | No ejecutado | pendiente | por completar | PENDIENTE | P3 |
| M-032 | Instalación limpia | VM Windows 10/11 | instalar/ejecutar | app y configurador operan | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-033 | Update | versión anterior instalada | aplicar update | preserva datos y exe real | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-034 | Rollback | forzar smoke failure | aplicar update | vuelve a versión previa | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-035 | Licencia renovada | config personalizada | instalar renovación | inicia y conserva configs | No ejecutado | pendiente | por completar | PENDIENTE | P1 |
| M-036 | Setup alterado/update alterado | modificar payload | ejecutar | rechazo por firma/hash | No ejecutado | pendiente | por completar | PENDIENTE | P1 |

## Evidencia requerida

- Captura o video con reloj visible.
- Log técnico redactado del caso.
- Hash SHA-256 del binario probado.
- Versión exacta de Windows, Lenel/navegador y lector.
- Identificador de equipo no personal.
- Conteo de iteraciones y archivo de resultados.
