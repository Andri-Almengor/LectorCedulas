import json
import os
import shutil
import sys
import threading
from datetime import datetime
from tkinter import Tk, Toplevel, messagebox, ttk

from assets.runtime import lector_core as core


ROOT = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(sys.argv[0]))
CFG = os.path.join(ROOT, "configs")
FORMS = os.path.join(CFG, "formularios")
SYSTEM = os.path.join(CFG, "sistema")
FORMATS = os.path.join(CFG, "formatos")
ACTIVE = os.path.join(SYSTEM, "config_actual.json")
FAVORITES = os.path.join(SYSTEM, "favoritos.json")
LAST_COM = os.path.join(SYSTEM, "ultimo_com.json")
DEFAULT_FORM = os.path.join(FORMS, "formulario_visitantes.json")

_lock = threading.RLock()
_selector_lock = threading.Lock()


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
    os.replace(temporary, path)


def _move_old(src, folder):
    if not os.path.isfile(src):
        return
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, os.path.basename(src))
    if os.path.exists(dst):
        try:
            with open(src, "rb") as source, open(dst, "rb") as target:
                if source.read() == target.read():
                    os.remove(src)
                    return
        except Exception:
            pass
        stem, extension = os.path.splitext(dst)
        dst = f"{stem}_migrada_{datetime.now():%Y%m%d_%H%M%S}{extension}"
    shutil.move(src, dst)


def migrate():
    for folder in (FORMS, SYSTEM, FORMATS):
        os.makedirs(folder, exist_ok=True)

    for name, folder in (
        ("config_actual.json", SYSTEM),
        ("ultimo_com.json", SYSTEM),
        ("favoritos.json", SYSTEM),
        ("formatos_cedulas.json", FORMATS),
    ):
        _move_old(os.path.join(CFG, name), folder)

    for name in os.listdir(CFG):
        path = os.path.join(CFG, name)
        if os.path.isfile(path) and name.lower().endswith(".json"):
            _move_old(path, FORMS)


def list_forms():
    os.makedirs(FORMS, exist_ok=True)
    return sorted(
        (name for name in os.listdir(FORMS) if name.lower().endswith(".json")),
        key=str.lower,
    )


def active_name():
    name = os.path.basename(str(read_json(ACTIVE, {}).get("activa", "")))
    available = list_forms()
    return name if name in available else (available[0] if available else "")


def set_active(name):
    name = os.path.basename(name or "")
    if name not in list_forms():
        raise ValueError("La configuración no existe.")
    with _lock:
        write_json(ACTIVE, {"activa": name})


def favorite_names():
    data = read_json(FAVORITES, {})
    available = set(list_forms())
    first = os.path.basename(str(data.get("favorito_1", "")))
    second = os.path.basename(str(data.get("favorito_2", "")))
    return (
        first if first in available else "",
        second if second in available else "",
    )


def initialize(hotkey="Ctrl+Alt+C"):
    migrate()
    if not os.path.exists(DEFAULT_FORM):
        write_json(
            DEFAULT_FORM,
            {
                "nombre": "Formulario Visitantes",
                "campos": [
                    {"dato": "Primer Apellido", "tabuladores": 0},
                    {"dato": "Nombre", "tabuladores": 0},
                    {"dato": "Cedula", "tabuladores": 1},
                    {"dato": "Fecha de Nacimiento", "tabuladores": 2},
                ],
            },
        )
    available = list_forms()
    if available and not os.path.exists(ACTIVE):
        set_active(available[0])
    if not os.path.exists(FAVORITES):
        write_json(FAVORITES, {"favorito_1": "", "favorito_2": "", "atajo": hotkey})


def load_active():
    try:
        name = active_name()
        if not name:
            return None
        with open(os.path.join(FORMS, name), "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as error:
        core.guardar_log(f"⚠️ Error cargando configuración: {error}")
        return None


def load_last_com():
    port = str(read_json(LAST_COM, {}).get("puerto", "")).strip()
    return port or None


def save_last_com(port):
    write_json(LAST_COM, {"puerto": str(port).strip(), "fecha": datetime.now().isoformat()})


class ConfigSelector:
    def __init__(self, parent=None, stop_event=None, hotkey="Ctrl+Alt+C"):
        self.stop_event = stop_event
        self.window = Toplevel(parent) if parent else Tk()
        self.window.title("Seleccionar configuración")
        self.window.geometry("460x275")
        self.window.resizable(False, False)
        self.window.configure(bg=core.COLOR_BG)
        try:
            self.window.iconbitmap(default=core.ICON_ASSETS_PATH)
        except Exception:
            pass

        style = ttk.Style(self.window)
        style.theme_use("clam")
        style.configure("DMS.TFrame", background=core.COLOR_BG)
        style.configure("DMS.TLabel", background=core.COLOR_BG, foreground="white", font=("Segoe UI", 11))
        style.configure(
            "DMS.TButton",
            background=core.COLOR_ACCENT,
            foreground="white",
            font=("Segoe UI", 10, "bold"),
            padding=7,
        )

        frame = ttk.Frame(self.window, padding=22, style="DMS.TFrame")
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text="Seleccione la configuración activa:",
            style="DMS.TLabel",
        ).pack(anchor="w", pady=(8, 8))

        available = list_forms()
        if not available:
            messagebox.showerror(
                "Sin configuraciones",
                "No hay formularios disponibles.",
                parent=self.window,
            )
            self.window.destroy()
            return

        self.combo = ttk.Combobox(frame, values=available, state="readonly", width=48)
        self.combo.pack(fill="x", pady=(0, 12))
        self.combo.set(active_name())

        first, second = favorite_names()
        ttk.Label(
            frame,
            text=f"Favoritas: {first or 'sin definir'} ↔ {second or 'sin definir'}\nAtajo: {hotkey}",
            style="DMS.TLabel",
        ).pack(anchor="w", pady=(0, 15))
        ttk.Button(
            frame,
            text="Activar",
            style="DMS.TButton",
            command=self.save,
        ).pack()

        self.window.after(250, self._watch_stop)
        self.window.grab_set()
        self.window.focus_force()
        self.window.wait_window()

    def _watch_stop(self):
        if self.stop_event is not None and self.stop_event.is_set():
            try:
                self.window.destroy()
            except Exception:
                pass
            return
        try:
            self.window.after(250, self._watch_stop)
        except Exception:
            pass

    def save(self):
        try:
            set_active(self.combo.get())
            self.window.destroy()
        except Exception as error:
            messagebox.showerror("Error", str(error), parent=self.window)


def open_selector(stop_event, hotkey="Ctrl+Alt+C"):
    if stop_event.is_set() or not _selector_lock.acquire(blocking=False):
        return

    def worker():
        try:
            root = Tk()
            root.withdraw()
            ConfigSelector(root, stop_event=stop_event, hotkey=hotkey)
            root.destroy()
        except Exception as error:
            core.guardar_log(f"⚠️ Error abriendo selector: {error}")
        finally:
            _selector_lock.release()

    threading.Thread(
        target=worker,
        name="DMSConfigSelector",
        daemon=True,
    ).start()
