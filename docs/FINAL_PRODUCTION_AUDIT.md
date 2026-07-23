# Auditoría final de producción — Lector de Cédulas DMS

Versión auditada: `4.0.0-qa7`

## Alcance

Esta revisión cubre el flujo completo:

1. detección y calibración del puerto COM;
2. recepción y delimitación de bytes;
3. reconocimiento de formatos;
4. validación semántica de datos;
5. selección de configuración;
6. captura de ventana objetivo;
7. cola y orden de trabajos;
8. escritura por portapapeles o `SendInput` Unicode;
9. atajos globales;
10. permanencia y recuperación del proceso;
11. licencias, dashboard, instalador y actualizador;
12. logs, diagnósticos y privacidad;
13. pruebas automatizadas y matriz física.

## Evidencia física reportada

El usuario reportó para `qa6`:

- múltiples lecturas completas y correctas;
- lectura de distintos tipos de cédula;
- cambio de configuración normal y rápida funcionando;
- aplicación estable, sin cierre después de varias lecturas;
- una única escritura parcial que terminó en el valor `119` dentro del campo de cédula;
- varias escrituras posteriores de solo cédula correspondientes al modo rápido.

Estos resultados son evidencia de campo aportada por el usuario. No sustituyen una ejecución automatizada ni una prueba física reproducida por CI.

## Hallazgos y correcciones

### 1. Cambio de configuración podía cortar una escritura iniciada

**Hallazgo:** `cancel_for_configuration_change()` activaba el evento de cancelación del trabajo actual. Si `Ctrl+Alt+C` o el menú cambiaban la configuración mientras se escribía la cédula, la transacción podía detenerse después de algunos caracteres.

**Impacto:** formulario parcialmente modificado, por ejemplo una cédula reducida a `119`.

**Corrección:**

- el trabajo que ya está escribiendo conserva su snapshot y termina completo;
- los trabajos todavía pendientes de la generación anterior se descartan;
- la cancelación inmediata queda reservada para `Ctrl+Alt+Esc` o cierre explícito.

### 2. Delimitación serial demasiado sensible a un silencio breve

**Hallazgo:** una única pausa de aproximadamente 180 ms terminaba el frame.

**Impacto:** lectores USB/serial con entrega fragmentada podían generar dos tramas a partir de una cédula.

**Corrección:**

- primera ventana de silencio;
- segunda ventana de estabilización;
- cualquier fragmento tardío reinicia la estabilización y se agrega al mismo frame;
- métrica y log `serial_late_fragment`.

### 3. La ventana objetivo se capturaba al terminar la lectura

**Hallazgo:** el contexto se capturaba después de recibir todos los bytes.

**Impacto:** un cambio de foco durante el escaneo podía asociar la cédula con otra ventana.

**Corrección:** la identidad HWND/PID/root HWND se captura cuando llega el primer bloque de bytes.

### 4. Parsing concurrente podía alterar el orden físico

**Hallazgo:** cuatro workers procesaban lecturas en paralelo. Una consulta TSE lenta podía terminar después de una lectura posterior.

**Impacto:** orden de escritura diferente al orden de escaneo.

**Corrección:** pipeline de parsing de un solo worker, conservando el orden físico. La escritura continúa desacoplada mediante la cola.

### 5. Reconocimiento no equivalía a datos suficientes para el formulario

**Hallazgo:** algunos formatos reconocidos contienen únicamente cédula o URL. El formulario completo podía preservar valores anteriores en campos no disponibles.

**Impacto:** combinación accidental entre una nueva identificación y datos antiguos del formulario.

**Corrección:** compuerta de calidad en dos niveles:

- calidad semántica del parser;
- requisitos de la configuración activa.

El modo rápido de solo `Cedula` acepta identificadores válidos. El formulario completo exige los campos que intenta escribir.

### 6. Validación semántica inconsistente

**Hallazgo:** rutas heredadas aceptaban identificaciones de cinco dígitos y algunas fechas se validaban antes de convertirlas.

**Corrección:**

- cédula de 9 a 12 dígitos;
- fecha real `DD/MM/YYYY`;
- años dentro de 1900–2100;
- nacimiento no futuro;
- emisión no futura;
- nombres sin valores `DESCONOCIDO`, `N/A`, `NULL` cuando el formulario los requiere.

### 7. Respaldo Unicode sin vigilancia continua del foco

**Hallazgo:** si el portapapeles no podía utilizarse, el respaldo escribía caracteres sin validar la ventana antes de cada uno.

**Impacto:** cambio de foco durante un campo podía enviar el resto del texto a otra aplicación.

**Corrección:** validación del objetivo exacto antes de cada carácter, después de cada campo y antes/después de un pegado atómico.

### 8. Carrera entre selección de configuración y creación del trabajo

**Hallazgo:** la configuración podía cambiar entre la validación de datos y el submit a la cola.

**Corrección:** snapshot, validación y enqueue se serializan con la transición de configuración.

### 9. Reinicio serial podía superponerse con el hilo anterior

**Hallazgo:** `stop()` cerraba el puerto pero no esperaba necesariamente el final del hilo.

**Corrección:** cierre con `join`, timeout y log técnico. Una instancia detenida no puede reutilizarse.

### 10. Actualizador comprobaba indirectamente el cierre

**Hallazgo:** abrir el EXE en modo escritura no demuestra que worker y supervisor hayan terminado.

**Corrección:** espera explícita por liberación de ambos mutex antes de reemplazar archivos. Si no se liberan, no se toca la instalación.

### 11. Cobertura de empaquetado insuficiente

**Hallazgo:** CI comprobaba Python y Ruff, pero no resolvía el grafo final de PyInstaller.

**Corrección:** job Windows 3.12 que genera un EXE smoke de más de 1 MB y valida el artefacto.

## Propiedades esperadas después de `qa7`

- Una escritura iniciada no se corta por cambiar de configuración.
- Las próximas lecturas usan la nueva configuración.
- Una lectura incompleta no modifica el formulario.
- El orden de escritura coincide con el orden de escaneo.
- La pérdida de foco detiene la entrega inmediatamente.
- El proceso se recupera de una caída inesperada.
- La salida manual no provoca reinicio.
- Un update no reemplaza archivos mientras haya procesos activos.
- No se registran datos personales en texto plano en logs técnicos nuevos.

## Matriz física final requerida

### Lectura y estrés

- 100 lecturas completas consecutivas.
- 30 lecturas con intervalos menores de un segundo.
- 30 lecturas dejando entre 3 y 5 segundos.
- cédula adulta clásica;
- cédula de menor;
- CSV extendida;
- código corto;
- QR TSE con y sin conectividad;
- mDoc soportado;
- formato binario bloqueado.

### Cambio de configuración

- activar `Ctrl+Alt+C` mientras una cédula está escribiendo;
- confirmar que esa escritura termina completa;
- confirmar que la siguiente utiliza la configuración nueva;
- repetir desde el menú;
- probar `Ctrl+Alt+Esc` y confirmar cancelación inmediata visible.

### Ventanas y foco

- Bloc de notas clásico/moderno;
- navegador;
- WinForms;
- LenelS2 OnGuard real;
- cambiar de foco deliberadamente durante una escritura y comprobar que se detiene.

### Permanencia

- una hora sin uso;
- suspender y reanudar Windows;
- bloquear y desbloquear sesión;
- desconectar y conectar el lector;
- cambiar el lector a otro puerto COM;
- finalizar manualmente solo el proceso worker y confirmar recuperación.

### Instalación y actualización

- instalación limpia;
- actualización sobre `qa6` preservando licencia y configuraciones;
- rollback provocado con paquete inválido;
- acceso directo de escritorio;
- inicio automático con Windows;
- desinstalación con aplicación ejecutándose.

## Criterio de liberación

No existe una garantía absoluta de ausencia de fallos en hardware, Windows o Lenel. La liberación puede considerarse apta cuando:

- GitHub Actions esté completamente verde;
- el build smoke de PyInstaller sea exitoso;
- la matriz física prioritaria no produzca datos parciales;
- no existan reinicios inesperados durante una hora;
- cualquier pérdida de foco o trama incompleta sea rechazada antes de modificar el formulario.
