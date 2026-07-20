import os
import sys
import json
import base64
import time
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import serial
import serial.tools.list_ports

APP_TITLE = "DMS - Capturador de otras cédulas"
COLOR_BG = "#212121"
COLOR_PANEL = "#2a2a2a"
COLOR_TEXT = "white"
COLOR_ACCENT = "#e53935"
ICON_PATH = os.path.join(os.path.dirname(sys.argv[0]), "assets", "DMS_icono_circulo_i.ico")
SALIDA_DIR = "lecturas_otras_cedulas"


def decode_preview(raw: bytes) -> str:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def list_ports():
    return [p.device for p in serial.tools.list_ports.comports()]


class Capturador(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("920x620")
        self.minsize(860, 560)
        self.configure(bg=COLOR_BG)
        self.raw = b""
        try:
            if os.path.exists(ICON_PATH):
                self.iconbitmap(default=ICON_PATH)
        except Exception:
            pass
        self._build_style()
        self._build_ui()
        self.refresh_ports()

    def _build_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("App.TFrame", background=COLOR_BG)
        style.configure("Panel.TFrame", background=COLOR_PANEL)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=("Segoe UI", 11))
        style.configure("Header.TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=("Segoe UI", 18, "bold"))
        style.configure("TButton", background=COLOR_ACCENT, foreground="white", padding=7, font=("Segoe UI", 10, "bold"))
        style.map("TButton", background=[("active", "#c62828")])
        style.configure("TCombobox", fieldbackground="white", foreground="black")
        style.configure("TEntry", fieldbackground="white", foreground="black")

    def _build_ui(self):
        root = ttk.Frame(self, style="App.TFrame", padding=16)
        root.pack(fill="both", expand=True)
        head = ttk.Frame(root, style="App.TFrame")
        head.pack(fill="x", pady=(0, 12))
        try:
            from PIL import Image, ImageTk
            if os.path.exists(ICON_PATH):
                img = Image.open(ICON_PATH).resize((52, 52))
                self.logo = ImageTk.PhotoImage(img)
                ttk.Label(head, image=self.logo, background=COLOR_BG).pack(side="left", padx=(0, 12))
        except Exception:
            pass
        title_box = ttk.Frame(head, style="App.TFrame")
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="Capturador de lecturas", style="Header.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="Herramienta independiente para capturar RAW/TEXTO/HEX/Base64 de cédulas no soportadas.").pack(anchor="w")

        controls = ttk.Frame(root, style="App.TFrame")
        controls.pack(fill="x", pady=(0, 10))
        ttk.Label(controls, text="Puerto COM:").pack(side="left")
        self.port_var = tk.StringVar()
        self.port_cb = ttk.Combobox(controls, textvariable=self.port_var, width=18, state="readonly")
        self.port_cb.pack(side="left", padx=8)
        ttk.Button(controls, text="Refrescar", command=self.refresh_ports).pack(side="left")
        ttk.Label(controls, text="Segundos:").pack(side="left", padx=(18, 4))
        self.seconds_var = tk.StringVar(value="8")
        ttk.Entry(controls, textvariable=self.seconds_var, width=5).pack(side="left")
        ttk.Button(controls, text="Capturar lectura", command=self.capture_async).pack(side="left", padx=12)
        ttk.Button(controls, text="Guardar JSON", command=self.save_json).pack(side="right")

        meta = ttk.Frame(root, style="App.TFrame")
        meta.pack(fill="x", pady=(0, 10))
        ttk.Label(meta, text="Tipo/nota:").pack(side="left")
        self.note_var = tk.StringVar(value="cedula_no_identificada")
        ttk.Entry(meta, textvariable=self.note_var, width=36).pack(side="left", padx=8)
        self.status_var = tk.StringVar(value="Listo.")
        ttk.Label(meta, textvariable=self.status_var).pack(side="left", padx=16)

        paned = ttk.Panedwindow(root, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned, style="Panel.TFrame", padding=8)
        right = ttk.Frame(paned, style="Panel.TFrame", padding=8)
        paned.add(left, weight=1)
        paned.add(right, weight=1)
        ttk.Label(left, text="Texto detectado / preview:", background=COLOR_PANEL).pack(anchor="w")
        self.txt_preview = tk.Text(left, wrap="word", bg="#111", fg="white", insertbackground="white")
        self.txt_preview.pack(fill="both", expand=True, pady=(6, 0))
        ttk.Label(right, text="HEX:", background=COLOR_PANEL).pack(anchor="w")
        self.txt_hex = tk.Text(right, wrap="word", bg="#111", fg="white", insertbackground="white")
        self.txt_hex.pack(fill="both", expand=True, pady=(6, 0))

    def refresh_ports(self):
        ports = list_ports()
        self.port_cb["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])
        self.status_var.set(f"Puertos encontrados: {len(ports)}")

    def capture_async(self):
        t = threading.Thread(target=self.capture, daemon=True)
        t.start()

    def capture(self):
        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("Puerto", "Seleccione un puerto COM.")
            return
        try:
            seconds = max(1, int(self.seconds_var.get() or "8"))
        except Exception:
            seconds = 8
        self.status_var.set(f"Escuchando {port}... pase la cédula")
        raw = bytearray()
        try:
            with serial.Serial(port, baudrate=9600, timeout=0.2) as ser:
                ser.reset_input_buffer()
                start = time.time()
                while time.time() - start < seconds:
                    if ser.in_waiting:
                        raw.extend(ser.read(ser.in_waiting))
                    time.sleep(0.01)
        except Exception as e:
            self.status_var.set("Error de lectura")
            messagebox.showerror("Error", f"No se pudo leer {port}:\n{e}")
            return
        self.raw = bytes(raw)
        preview = decode_preview(self.raw)
        hx = self.raw.hex(" ")
        self.txt_preview.delete("1.0", tk.END)
        self.txt_preview.insert(tk.END, preview)
        self.txt_hex.delete("1.0", tk.END)
        self.txt_hex.insert(tk.END, hx)
        self.status_var.set(f"Lectura capturada: {len(self.raw)} bytes")

    def save_json(self):
        if not self.raw:
            messagebox.showwarning("Sin lectura", "Primero capture una lectura.")
            return
        os.makedirs(SALIDA_DIR, exist_ok=True)
        note = (self.note_var.get() or "cedula_no_identificada").strip().replace(" ", "_")
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{note}.json"
        path = filedialog.asksaveasfilename(initialdir=SALIDA_DIR, initialfile=filename, defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        payload = {
            "nota": self.note_var.get(),
            "puerto": self.port_var.get(),
            "fecha": datetime.now().isoformat(),
            "bytes_len": len(self.raw),
            "texto_preview": decode_preview(self.raw),
            "hex": self.raw.hex(" "),
            "base64": base64.b64encode(self.raw).decode("ascii"),
            "uso": "Enviar este JSON como muestra para crear un nuevo parser y agregarlo al lector principal."
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        messagebox.showinfo("Guardado", f"Lectura guardada en:\n{path}")


if __name__ == "__main__":
    Capturador().mainloop()
