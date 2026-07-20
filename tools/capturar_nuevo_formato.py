import os
import sys
import json
import time
import base64
import queue
import threading
import serial
import serial.tools.list_ports
from datetime import datetime
from tkinter import Tk, ttk, messagebox, StringVar

CONFIG_DIR = "configs"
FORMATOS_FILE = os.path.join(CONFIG_DIR, "formatos_cedulas.json")
SALIDA_DIR = os.path.join("logs", "diagnosticos_formatos")
BAUDRATE = 9600
READ_IDLE_SECONDS = 0.80
READ_TIMEOUT_TOTAL = 12
READ_MAX_BYTES = 1600
MIN_BYTES_VALIDOS = 8

PROMPT_PARA_CHATGPT = """
PROMPT PARA AGREGAR UN NUEVO FORMATO AL LECTOR DMS

Actúa como desarrollador Python del sistema lector de cédulas DMS.
Te voy a cargar este TXT y el archivo configs/formatos_cedulas.json actual.
Necesito que analices las muestras RAW del documento nuevo y me devuelvas SOLO el JSON completo de formatos_cedulas.json con un nuevo formato agregado, sin eliminar los formatos existentes.

Reglas importantes:
1. No inventes datos personales. Usa únicamente patrones visibles en las muestras.
2. Si el documento es binario, analiza raw_hex y raw_base64 para encontrar posiciones, longitudes, separadores o codificación.
3. Si es texto, detecta delimitadores, orden de campos y formato de fecha.
4. Mantén compatibilidad con estos campos estándar:
   - Cedula
   - Apellidos
   - Primer Apellido
   - Segundo Apellido
   - Nombre
   - Sexo
   - Fecha de Nacimiento
   - Fecha de Expiracion
   - Fecha de Expiración
   - Fecha de Emision
   - Lugar de Nacimiento
   - Lugar de Residencia
   - Padre
   - Madre
5. Si el sexo no se puede determinar de forma confiable, déjalo como DESCONOCIDO y no hagas que falle la lectura.
6. El nuevo formato debe tener enabled=true, id único, tipo soportado por el main.py y required mínimo para evitar que licencias u otros documentos se escriban como cédulas.
7. Devuelve el JSON completo listo para reemplazar configs/formatos_cedulas.json.
""".strip()


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def decode_attempts(raw: bytes):
    results = {}
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            results[enc] = raw.decode(enc, errors="replace")
        except Exception as e:
            results[enc] = f"ERROR: {e}"
    return results


def byte_table(raw: bytes, limit=320):
    lines = []
    lines.append("idx_dec | idx_hex | byte_hex | ascii_latin1")
    lines.append("--------|---------|----------|-------------")
    for i, b in enumerate(raw[:limit]):
        ch = chr(b)
        if ch in "\r\n\t":
            show = repr(ch)[1:-1]
        elif 32 <= b <= 126 or b >= 160:
            show = ch
        else:
            show = "."
        lines.append(f"{i:7d} | 0x{i:04X}  | 0x{b:02X}    | {show}")
    if len(raw) > limit:
        lines.append(f"... truncado en tabla: {limit} de {len(raw)} bytes ...")
    return "\n".join(lines)


def cargar_formatos_actuales():
    path = os.path.join(app_dir(), FORMATOS_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            return {"error": f"No se pudo leer {FORMATOS_FILE}: {e}"}
    return {"aviso": f"No existe {FORMATOS_FILE}. Ejecuta main.py una vez para crearlo."}


def leer_buffer_serial(ser):
    """Lee una sola pasada completa sin congelar la GUI. Se ejecuta en hilo aparte."""
    buffer = bytearray()
    start = time.time()
    last_data = None

    while time.time() - start < READ_TIMEOUT_TOTAL:
        waiting = ser.in_waiting
        if waiting:
            chunk = ser.read(waiting)
            if chunk:
                buffer.extend(chunk)
                last_data = time.time()
                if buffer.endswith(b"\r\n") or buffer.endswith(b"\n"):
                    time.sleep(0.05)
                    if not ser.in_waiting:
                        break
                if len(buffer) >= READ_MAX_BYTES:
                    break
        else:
            if buffer and last_data and (time.time() - last_data) >= READ_IDLE_SECONDS:
                time.sleep(0.10)
                if not ser.in_waiting:
                    break
        time.sleep(0.005)

    return bytes(buffer)


def capturar_en_puerto(puerto, callback):
    try:
        callback(f"Abriendo {puerto}. Pase UNA vez el documento por el lector...")
        with serial.Serial(puerto, baudrate=BAUDRATE, timeout=0.2) as ser:
            ser.reset_input_buffer()
            raw = leer_buffer_serial(ser)
            ser.reset_input_buffer()
        if raw and len(raw) >= MIN_BYTES_VALIDOS:
            callback(f"Lectura capturada en {puerto}: {len(raw)} bytes")
            return puerto, raw
        callback(f"No llegó información suficiente desde {puerto}.")
        return None
    except Exception as e:
        callback(f"Error en {puerto}: {e}")
        return None


def guardar_diagnostico(raw: bytes, puerto: str):
    salida_abs = os.path.join(app_dir(), SALIDA_DIR)
    os.makedirs(salida_abs, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(salida_abs, f"diagnostico_formato_{ts}.txt")
    attempts = decode_attempts(raw)
    formatos = cargar_formatos_actuales()

    content = []
    content.append(PROMPT_PARA_CHATGPT)
    content.append("\n\n==================== METADATOS ====================")
    content.append(f"Fecha: {datetime.now().isoformat()}")
    content.append(f"Puerto COM: {puerto}")
    content.append(f"Longitud bytes: {len(raw)}")
    content.append("\n==================== RAW BASE64 ====================")
    content.append(base64.b64encode(raw).decode("ascii"))
    content.append("\n==================== RAW HEX ====================")
    content.append(raw.hex())
    content.append("\n==================== DECODIFICACIONES DE PRUEBA ====================")
    for enc, txt in attempts.items():
        content.append(f"\n--- {enc} ---")
        content.append(txt[:5000])
    content.append("\n==================== TABLA DE BYTES ====================")
    content.append(byte_table(raw))
    content.append("\n==================== FORMATOS_CEDULAS_JSON_ACTUAL ====================")
    content.append(json.dumps(formatos, indent=2, ensure_ascii=False))

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(content))
    return path


def listar_puertos():
    return [p.device for p in serial.tools.list_ports.comports()]


def main():
    root = Tk()
    root.title("DMS - Capturar nuevo formato de documento")
    root.geometry("700x330")
    root.resizable(False, False)

    q = queue.Queue()
    working = {"value": False}

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame,
        text="Pase UNA sola vez el documento nuevo por el lector.\nEsta herramienta no escribe en ningún formulario; solo captura el RAW para análisis.",
        font=("Segoe UI", 11),
    ).pack(pady=(0, 15))

    row = ttk.Frame(frame)
    row.pack(fill="x", pady=(0, 12))

    ttk.Label(row, text="Puerto COM:").pack(side="left")
    com_var = StringVar()
    combo = ttk.Combobox(row, textvariable=com_var, state="readonly", width=18)
    combo.pack(side="left", padx=(8, 8))

    def refrescar_puertos():
        puertos = listar_puertos()
        combo["values"] = puertos
        if puertos and not com_var.get():
            com_var.set(puertos[0])
        elif not puertos:
            com_var.set("")
        status.config(text="Puertos actualizados." if puertos else "No hay puertos COM disponibles.")

    ttk.Button(row, text="Actualizar puertos", command=refrescar_puertos).pack(side="left")

    status = ttk.Label(frame, text="Listo para iniciar.", wraplength=640)
    status.pack(pady=(0, 12), fill="x")

    progress = ttk.Progressbar(frame, mode="indeterminate")
    progress.pack(fill="x", pady=(0, 14))

    def set_status(msg):
        q.put(("status", msg))

    def worker(puerto):
        try:
            result = capturar_en_puerto(puerto, set_status)
            if not result:
                q.put(("warning", "No se capturó ningún documento. Intente de nuevo."))
                return
            puerto_ok, raw = result
            path = guardar_diagnostico(raw, puerto_ok)
            q.put(("done", path))
        except Exception as e:
            q.put(("error", str(e)))
        finally:
            q.put(("finished", None))

    def iniciar():
        if working["value"]:
            return
        puerto = com_var.get().strip()
        if not puerto:
            messagebox.showwarning("Sin puerto", "Seleccione un puerto COM primero.")
            return
        working["value"] = True
        btn.config(state="disabled")
        progress.start(10)
        status.config(text=f"Esperando lectura en {puerto}. Pase el documento una sola vez...")
        threading.Thread(target=worker, args=(puerto,), daemon=True).start()

    btn = ttk.Button(frame, text="Capturar documento nuevo", command=iniciar)
    btn.pack()

    def procesar_queue():
        try:
            while True:
                tipo, payload = q.get_nowait()
                if tipo == "status":
                    status.config(text=payload)
                elif tipo == "warning":
                    messagebox.showwarning("Sin lectura", payload)
                elif tipo == "error":
                    messagebox.showerror("Error", payload)
                elif tipo == "done":
                    status.config(text=f"Diagnóstico creado:\n{payload}")
                    try:
                        os.startfile(payload)
                    except Exception:
                        pass
                    messagebox.showinfo(
                        "Diagnóstico creado",
                        f"Se creó el archivo:\n{payload}\n\nCárgalo a ChatGPT junto con formatos_cedulas.json para agregar el nuevo formato.",
                    )
                elif tipo == "finished":
                    working["value"] = False
                    btn.config(state="normal")
                    progress.stop()
        except queue.Empty:
            pass
        root.after(100, procesar_queue)

    refrescar_puertos()
    root.after(100, procesar_queue)
    root.mainloop()


if __name__ == "__main__":
    main()
