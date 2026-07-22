from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from assets.runtime import editor_core as legacy
from assets.runtime.hardened.atomic_io import read_json, write_json_atomic
from assets.runtime.hardened.config_service import ConfigurationError, ConfigurationService, migrate_configuration, validate_configuration

HOTKEY = "Ctrl+Alt+C"
ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CFG = ROOT / "configs"
FORMS = CFG / "formularios"
SYSTEM = CFG / "sistema"
ACTIVE = SYSTEM / "config_actual.json"
FAVORITES = SYSTEM / "favoritos.json"
BG = "#212121"
PANEL = "#2a2a2a"
RED = "#e53935"
service = ConfigurationService(CFG)


def _legacy_base(filename: str) -> str:
    return filename[:-5] if filename.casefold().endswith(".json") else filename


def _harden_form(filename: str) -> None:
    path = FORMS / os.path.basename(filename)
    payload = read_json(path, required=True)
    migrated = migrate_configuration(payload, fallback_name=path.stem)
    validate_configuration(migrated, source_path=str(path), generation=service.generation)
    write_json_atomic(path, migrated)


def _favorites() -> tuple[str, str]:
    return service.favorites()


def _save_favorites(first: str, second: str) -> None:
    available = set(service.list_forms())
    if first not in available or second not in available:
        raise ConfigurationError("Seleccione dos configuraciones existentes")
    if first == second:
        raise ConfigurationError("Las favoritas deben ser diferentes")
    write_json_atomic(FAVORITES, {"favorito_1": first, "favorito_2": second, "atajo": HOTKEY})


def _replace_references(old: str, new: str = "") -> None:
    data = read_json(FAVORITES, default={}) or {}
    first = os.path.basename(str(data.get("favorito_1") or ""))
    second = os.path.basename(str(data.get("favorito_2") or ""))
    changed = False
    if first == old:
        first = new
        changed = True
    if second == old:
        second = new
        changed = True
    if changed:
        write_json_atomic(FAVORITES, {"favorito_1": first, "favorito_2": second, "atajo": HOTKEY})
    try:
        active = os.path.basename(str((read_json(ACTIVE, required=True) or {}).get("activa") or ""))
    except Exception:
        active = ""
    if active == old:
        if new:
            service.set_active(new)
        else:
            write_json_atomic(ACTIVE, {"activa": ""})


class Manager(tk.Tk):
    def __init__(self):
        super().__init__()
        service.initialize()
        legacy.CONFIG_DIR = str(FORMS)
        self.title("DMS - Configuraciones")
        self.geometry("850x520")
        self.minsize(780, 480)
        self.configure(bg=BG)
        self._styles()
        self._build()
        self.refresh()

    def _styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("A.TFrame", background=BG)
        style.configure("P.TFrame", background=PANEL)
        style.configure("H.TLabel", background=BG, foreground="white", font=("Segoe UI", 18, "bold"))
        style.configure("A.TLabel", background=BG, foreground="white", font=("Segoe UI", 10))
        style.configure("P.TLabel", background=PANEL, foreground="white", font=("Segoe UI", 10))
        style.configure("R.TButton", background=RED, foreground="white", font=("Segoe UI", 10, "bold"), padding=8)
        style.configure("G.TButton", background="#3a3a3a", foreground="white", font=("Segoe UI", 10), padding=8)
        style.configure("D.TButton", background="#b71c1c", foreground="white", font=("Segoe UI", 10), padding=8)

    def _build(self):
        root = ttk.Frame(self, style="A.TFrame", padding=18)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="Configuraciones de formularios", style="H.TLabel").pack(anchor="w")
        ttk.Label(root, text="Tabuladores = movimientos adicionales antes del campo. La acción posterior y la acción final se muestran en la vista previa.", style="A.TLabel", wraplength=800).pack(anchor="w", pady=(2, 14))
        card = ttk.Frame(root, style="P.TFrame", padding=14)
        card.pack(fill="x")
        ttk.Label(card, text="Configuración:", style="P.TLabel").grid(row=0, column=0, sticky="w")
        self.selected = tk.StringVar()
        self.combo = ttk.Combobox(card, textvariable=self.selected, state="readonly", width=60)
        self.combo.grid(row=1, column=0, sticky="ew", pady=(5, 10))
        card.grid_columnconfigure(0, weight=1)
        buttons = ttk.Frame(card, style="P.TFrame")
        buttons.grid(row=2, column=0, sticky="ew")
        ttk.Button(buttons, text="Crear nueva", style="R.TButton", command=self.create).pack(side="left")
        ttk.Button(buttons, text="Editar", style="G.TButton", command=self.edit).pack(side="left", padx=7)
        ttk.Button(buttons, text="Vista previa", style="G.TButton", command=self.preview).pack(side="left")
        ttk.Button(buttons, text="Probar configuración", style="G.TButton", command=self.test_configuration).pack(side="left", padx=7)
        ttk.Button(buttons, text="Activar", style="G.TButton", command=self.activate).pack(side="left")
        ttk.Button(buttons, text="Eliminar", style="D.TButton", command=self.delete).pack(side="right")
        fav = ttk.Frame(root, style="P.TFrame", padding=14)
        fav.pack(fill="x", pady=(14, 0))
        ttk.Label(fav, text=f"Favoritas para cambio rápido — atajo global {HOTKEY}", style="P.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self.f1 = tk.StringVar()
        self.f2 = tk.StringVar()
        self.c1 = ttk.Combobox(fav, textvariable=self.f1, state="readonly", width=30)
        self.c2 = ttk.Combobox(fav, textvariable=self.f2, state="readonly", width=30)
        self.c1.grid(row=1, column=0, sticky="ew")
        self.c2.grid(row=1, column=1, sticky="ew", padx=(12, 0))
        ttk.Button(fav, text="Guardar favoritas", style="R.TButton", command=self.save_favs).grid(row=1, column=2, padx=(12, 0))
        fav.grid_columnconfigure(0, weight=1)
        fav.grid_columnconfigure(1, weight=1)
        self.status = tk.StringVar()
        ttk.Label(root, textvariable=self.status, style="A.TLabel").pack(anchor="w", pady=(14, 0))

    def refresh(self, preferred=""):
        values = service.list_forms()
        for combo in (self.combo, self.c1, self.c2):
            combo["values"] = values
        current = preferred if preferred in values else self.selected.get()
        if current not in values:
            current = values[0] if values else ""
        self.selected.set(current)
        first, second = _favorites()
        self.f1.set(first)
        self.f2.set(second)
        try:
            active = Path(service.load_active().source_path).name
        except Exception:
            active = "INVÁLIDA — escritura bloqueada"
        self.status.set(f"Activa: {active} | Favoritas: {first or 'sin definir'} ↔ {second or 'sin definir'}")

    def create(self):
        before = set(service.list_forms())
        window = legacy.EditorConfig(self, modo="crear")
        self.wait_window(window)
        added = list(set(service.list_forms()) - before)
        try:
            for name in added:
                _harden_form(name)
        except Exception as exc:
            messagebox.showerror("Configuración inválida", str(exc), parent=self)
        self.refresh(added[0] if len(added) == 1 else "")

    def edit(self):
        old = self.selected.get()
        if not old:
            return
        before = set(service.list_forms())
        window = legacy.EditorConfig(self, modo="editar", nombre_existente=_legacy_base(old))
        self.wait_window(window)
        after = set(service.list_forms())
        new = list(after - before)
        selected = new[0] if old not in after and len(new) == 1 else old
        try:
            _harden_form(selected)
            if selected != old:
                _replace_references(old, selected)
        except Exception as exc:
            messagebox.showerror("Configuración inválida", str(exc), parent=self)
        self.refresh(selected)

    def _snapshot(self):
        name = self.selected.get()
        if not name:
            raise ConfigurationError("Seleccione una configuración")
        payload = read_json(FORMS / name, required=True)
        return validate_configuration(payload, source_path=str(FORMS / name), generation=service.generation)

    def preview(self):
        try:
            snapshot = self._snapshot()
            lines = []
            for index, field in enumerate(snapshot.fields, start=1):
                lines.append(f"{index}. +{field.tabs_before} Tab → {field.label} → {field.action_after.value} | vacío={field.empty_policy.value} | validación={field.validation.value}")
            lines.append(f"Acción final: {snapshot.final_action.value}")
            messagebox.showinfo("Vista previa de navegación", "\n".join(lines), parent=self)
        except Exception as exc:
            messagebox.showerror("Configuración inválida", str(exc), parent=self)

    def test_configuration(self):
        try:
            snapshot = self._snapshot()
        except Exception as exc:
            messagebox.showerror("Configuración inválida", str(exc), parent=self)
            return
        window = tk.Toplevel(self)
        window.title("Prueba sin cédula real")
        window.geometry("620x420")
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Prueba lógica con datos ficticios; no usa una cédula real.").pack(anchor="w", pady=(0, 10))
        entries = []
        for field in snapshot.fields:
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=field.label, width=25).pack(side="left")
            entry = ttk.Entry(row)
            entry.pack(side="left", fill="x", expand=True)
            entry.insert(0, f"PRUEBA_{field.label.upper().replace(' ', '_')}")
            entries.append(entry)
        if entries:
            entries[0].focus_set()
        ttk.Label(frame, text="Revise manualmente el orden con Tab. La prueba física del escritor debe registrarse en la matriz manual.", wraplength=570).pack(anchor="w", pady=(12, 0))

    def activate(self):
        name = self.selected.get()
        try:
            _harden_form(name)
            if not messagebox.askyesno("Confirmar activación", f"¿Activar '{name}'?\n\nLos trabajos pendientes de otra configuración serán cancelados por seguridad.", parent=self):
                return
            service.set_active(name)
            self.refresh(name)
            messagebox.showinfo("Activa", f"Configuración activa:\n{name}", parent=self)
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)

    def delete(self):
        name = self.selected.get()
        if not name or not messagebox.askyesno("Confirmar", f"¿Eliminar '{name}'?", parent=self):
            return
        try:
            (FORMS / name).unlink()
            _replace_references(name)
            self.refresh()
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)

    def save_favs(self):
        try:
            _save_favorites(self.f1.get(), self.f2.get())
            self.refresh(self.selected.get())
            messagebox.showinfo("Favoritas", f"Use {HOTKEY} para alternar entre ambas.", parent=self)
        except Exception as exc:
            messagebox.showerror("Favoritas", str(exc), parent=self)


if __name__ == "__main__":
    Manager().mainloop()
