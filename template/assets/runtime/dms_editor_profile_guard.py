import json
import os
import tkinter as tk
from tkinter import ttk

from assets.runtime import editor_core


PROFILE_LABELS = {
    "Rápida y precisa": "rapida",
    "Equilibrada": "equilibrada",
    "Máxima compatibilidad": "segura",
}
PROFILE_KEYS = {value: key for key, value in PROFILE_LABELS.items()}

_original_init = editor_core.EditorConfig.__init__
_original_load = editor_core.EditorConfig._cargar_existente
_original_save = editor_core.EditorConfig.guardar_config


def _atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _load_profile_settings(self, nombre_base):
    path = os.path.join(editor_core.CONFIG_DIR, nombre_base + ".json")
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        key = str(data.get("perfil_escritura", "rapida")).strip().casefold()
        self.var_perfil_escritura.set(PROFILE_KEYS.get(key, "Rápida y precisa"))
        self.var_validar_escritura.set(bool(data.get("validar_escritura", True)))
        self.var_reemplazar_contenido.set(bool(data.get("reemplazar_contenido", False)))
    except Exception:
        self.var_perfil_escritura.set("Rápida y precisa")
        self.var_validar_escritura.set(True)
        self.var_reemplazar_contenido.set(False)


def _profile_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)

    self.var_perfil_escritura = tk.StringVar(master=self, value="Rápida y precisa")
    self.var_validar_escritura = tk.BooleanVar(master=self, value=True)
    self.var_reemplazar_contenido = tk.BooleanVar(master=self, value=False)

    try:
        footer = self.winfo_children()[-1]
        settings = ttk.Frame(footer, style="TFrame")
        settings.pack(side="right")

        ttk.Label(settings, text="Velocidad:", style="TLabel").pack(side="left", padx=(0, 5))
        combo = ttk.Combobox(
            settings,
            textvariable=self.var_perfil_escritura,
            values=list(PROFILE_LABELS),
            state="readonly",
            width=22,
        )
        combo.pack(side="left", padx=(0, 10))
        ttk.Checkbutton(
            settings,
            text="Validar cuando sea posible",
            variable=self.var_validar_escritura,
        ).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(
            settings,
            text="Reemplazar contenido",
            variable=self.var_reemplazar_contenido,
        ).pack(side="left")
    except Exception:
        pass

    nombre_existente = kwargs.get("nombre_existente")
    if nombre_existente is None and len(args) >= 2:
        nombre_existente = args[1]
    if nombre_existente:
        _load_profile_settings(self, nombre_existente)


def _profile_load(self, nombre_base):
    _original_load(self, nombre_base)
    if hasattr(self, "var_perfil_escritura"):
        _load_profile_settings(self, nombre_base)


def _profile_save(self):
    name = self.entry_nombre.get().strip().replace(" ", "_")
    profile_label = self.var_perfil_escritura.get()
    validation = bool(self.var_validar_escritura.get())
    replace_existing = bool(self.var_reemplazar_contenido.get())

    _original_save(self)

    try:
        still_open = bool(self.winfo_exists())
    except Exception:
        still_open = False
    if still_open or not name:
        return

    path = os.path.join(editor_core.CONFIG_DIR, name + ".json")
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        data["perfil_escritura"] = PROFILE_LABELS.get(profile_label, "rapida")
        data["validar_escritura"] = validation
        data["reemplazar_contenido"] = replace_existing
        _atomic_write(path, data)
    except Exception:
        # La configuración de campos ya quedó guardada por el editor original.
        # No se bloquea al usuario si solo falla la escritura de preferencias.
        pass


if not getattr(editor_core.EditorConfig, "_dms_writer_profiles_installed", False):
    editor_core.EditorConfig.__init__ = _profile_init
    editor_core.EditorConfig._cargar_existente = _profile_load
    editor_core.EditorConfig.guardar_config = _profile_save
    editor_core.EditorConfig._dms_writer_profiles_installed = True
