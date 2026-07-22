from __future__ import annotations

import copy
import json
import re
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "template"
if str(TEMPLATE) not in sys.path:
    sys.path.insert(0, str(TEMPLATE))

try:
    from dateutil.relativedelta import relativedelta
except Exception:  # pragma: no cover - dependencia validada en requirements
    relativedelta = None

from assets.runtime.hardened.atomic_io import write_json_atomic  # noqa: E402
from assets.runtime.hardened.version import VERSION  # noqa: E402
from tools.release_builder import (  # noqa: E402
    export_client_license_bundle,
    make_installer_zip,
    make_update_zip,
)

APP_NAME = "DMS - Lector de Cédulas | Dashboard"
APP_VERSION = VERSION
CLIENTS_DIR = ROOT / "clientes"
DB_PATH = CLIENTS_DIR / "db_clientes.json"
ASSETS_DIR = TEMPLATE / "assets"

COLOR_BG = "#212121"
COLOR_PANEL = "#2a2a2a"
COLOR_INPUT = "#1e1e1e"
COLOR_TEXT = "white"
COLOR_ACCENT = "#e53935"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    normalized = (value or "").strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def client_id_from_name(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_")
    return slug.upper()[:40] or f"CLIENTE_{uuid.uuid4().hex[:6].upper()}"


def expiration_from_duration(duration: dict[str, int], *, base: datetime) -> datetime:
    years = int(duration.get("years", 0) or 0)
    months = int(duration.get("months", 0) or 0)
    days = int(duration.get("days", 0) or 0)
    hours = int(duration.get("hours", 0) or 0)
    if min(years, months, days, hours) < 0:
        raise ValueError("La duración no puede contener valores negativos")
    if not any((years, months, days, hours)):
        raise ValueError("La duración debe ser mayor que cero")
    result = base
    if years or months:
        if relativedelta is None:
            raise RuntimeError("Falta python-dateutil para calcular meses o años")
        result += relativedelta(years=years, months=months)
    return result + timedelta(days=days, hours=hours)


def load_db() -> dict:
    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        return {}
    try:
        data = json.loads(DB_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"No se pudo leer {DB_PATH}: {exc}") from exc
    if isinstance(data, list):
        migrated: dict[str, dict] = {}
        for row in data:
            cid = client_id_from_name(str(row.get("cliente") or ""))
            migrated[cid] = {
                "client_id": cid,
                "name": row.get("cliente") or cid,
                "license": {
                    "license_id": row.get("licencia") or f"LIC-{uuid.uuid4().hex[:12].upper()}",
                    "issued_at_utc": iso_z(now_utc()),
                    "expires_at_utc": row.get("expira") or iso_z(now_utc() + timedelta(days=1)),
                    "status": "active",
                },
                "build_history": [],
            }
        save_db(migrated)
        return migrated
    if not isinstance(data, dict):
        raise RuntimeError("La base de clientes debe ser un objeto JSON")
    return data


def save_db(db: dict) -> None:
    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
    write_json_atomic(DB_PATH, db, backup=True)


def license_status(expires_at_utc: str) -> tuple[str, int]:
    try:
        seconds = (parse_dt(expires_at_utc) - now_utc()).total_seconds()
    except Exception:
        return "DESCONOCIDA", 0
    if seconds <= 0:
        return "EXPIRADA", int(seconds // 86400)
    return "ACTIVA", int(seconds // 86400)


@dataclass(slots=True)
class ClientRow:
    client_id: str
    name: str
    license_id: str
    expires_at: str
    status: str
    days_left: int
    license_path: str


class DurationDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, title: str, *, include_action: bool = False):
        super().__init__(parent)
        self.result: tuple[str, dict[str, int]] | dict[str, int] | None = None
        self.title(title)
        self.configure(bg=COLOR_BG)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        self.include_action = include_action
        self.action = tk.StringVar(value="renew")
        if include_action:
            ttk.Label(frame, text="Acción").grid(row=0, column=0, sticky="w")
            ttk.Radiobutton(frame, text="Renovar desde hoy", variable=self.action, value="renew").grid(
                row=1, column=0, columnspan=2, sticky="w"
            )
            ttk.Radiobutton(
                frame,
                text="Extender desde la expiración",
                variable=self.action,
                value="extend",
            ).grid(row=2, column=0, columnspan=2, sticky="w")
            start_row = 3
        else:
            start_row = 0

        self.entries: dict[str, tk.Spinbox] = {}
        labels = (
            ("years", "Años", 30),
            ("months", "Meses", 120),
            ("days", "Días", 3650),
            ("hours", "Horas", 87600),
        )
        for index, (key, label, maximum) in enumerate(labels):
            ttk.Label(frame, text=label).grid(row=start_row, column=index, sticky="w", padx=(0, 8))
            entry = tk.Spinbox(frame, from_=0, to=maximum, width=7)
            entry.grid(row=start_row + 1, column=index, sticky="w", padx=(0, 8))
            self.entries[key] = entry
        self.entries["years"].delete(0, "end")
        self.entries["years"].insert(0, "1")

        buttons = ttk.Frame(frame)
        buttons.grid(row=start_row + 2, column=0, columnspan=4, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Aceptar", style="Primary.TButton", command=self._accept).pack(
            side="right", padx=8
        )

    def _accept(self) -> None:
        try:
            duration = {key: int(entry.get() or 0) for key, entry in self.entries.items()}
            expiration_from_duration(duration, base=now_utc())
        except Exception as exc:
            messagebox.showerror("Duración inválida", str(exc), parent=self)
            return
        self.result = (self.action.get(), duration) if self.include_action else duration
        self.destroy()


class NewClientDialog(DurationDialog):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent, "Nuevo cliente")
        frame = self.winfo_children()[0]
        for child in frame.grid_slaves():
            info = child.grid_info()
            child.grid_configure(row=int(info["row"]) + 2)
        ttk.Label(frame, text="Nombre del cliente").grid(row=0, column=0, columnspan=4, sticky="w")
        self.name_entry = ttk.Entry(frame, width=48)
        self.name_entry.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(2, 12))
        self.name_entry.focus_set()

    def _accept(self) -> None:
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("Dato requerido", "Escribe el nombre del cliente.", parent=self)
            return
        super()._accept()
        if self.result is not None:
            self.result = (name, self.result)


class Dashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1120x650")
        self.minsize(980, 580)
        self.configure(bg=COLOR_BG)
        self._apply_icon()
        self._build_style()
        try:
            self.db = load_db()
        except Exception as exc:
            messagebox.showerror("Base de clientes", str(exc))
            self.db = {}
        self._build_ui()
        self.refresh_table()

    def _apply_icon(self) -> None:
        icon = ASSETS_DIR / "DMS_icono_circulo_i.ico"
        try:
            if icon.exists():
                self.iconbitmap(default=str(icon))
        except Exception:
            pass

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=COLOR_BG)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("TLabelframe", background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("TLabelframe.Label", background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("TEntry", fieldbackground=COLOR_INPUT, foreground=COLOR_TEXT)
        style.configure("TCombobox", fieldbackground=COLOR_INPUT, foreground=COLOR_TEXT)
        style.configure("Primary.TButton", background=COLOR_ACCENT, foreground="white", padding=8)
        style.map("Primary.TButton", background=[("active", "#c62828")])
        style.configure(
            "Treeview",
            background="#1a1a1a",
            fieldbackground="#1a1a1a",
            foreground=COLOR_TEXT,
            rowheight=28,
        )
        style.configure("Treeview.Heading", background=COLOR_PANEL, foreground=COLOR_TEXT)
        style.map("Treeview", background=[("selected", "#3b0f0f")])

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="DMS Lector de Cédulas", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(root, text=f"Dashboard seguro • v{APP_VERSION} • licencias Ed25519 automáticas").pack(
            anchor="w", pady=(2, 12)
        )

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)
        clients_tab = ttk.Frame(notebook, padding=12)
        updates_tab = ttk.Frame(notebook, padding=12)
        notebook.add(clients_tab, text="Clientes y licencias")
        notebook.add(updates_tab, text="Actualizaciones")
        self._build_clients_tab(clients_tab)
        self._build_updates_tab(updates_tab)

    def _build_clients_tab(self, tab: ttk.Frame) -> None:
        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="➕ Nuevo cliente", style="Primary.TButton", command=self.create_client).pack(
            side="left"
        )
        ttk.Button(toolbar, text="♻️ Renovar/Extender", command=self.renew_license).pack(side="left", padx=8)
        ttk.Button(toolbar, text="🔐 Exportar licencia", command=self.export_license).pack(side="left")
        ttk.Button(
            toolbar,
            text="📦 Generar instalador",
            style="Primary.TButton",
            command=self.generate_installer,
        ).pack(side="right")
        ttk.Button(toolbar, text="🗑 Eliminar", command=self.delete_client).pack(side="right", padx=8)

        columns = ("client_id", "name", "license_id", "expires", "status", "days", "path")
        self.tree = ttk.Treeview(tab, columns=columns, show="headings")
        headings = {
            "client_id": "Client ID",
            "name": "Cliente",
            "license_id": "Licencia",
            "expires": "Expira (UTC)",
            "status": "Estado",
            "days": "Días",
            "path": "Archivo firmado",
        }
        widths = {
            "client_id": 130,
            "name": 210,
            "license_id": 160,
            "expires": 190,
            "status": 90,
            "days": 60,
            "path": 280,
        }
        for key in columns:
            self.tree.heading(key, text=headings[key])
            self.tree.column(key, width=widths[key], anchor="e" if key == "days" else "w")
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _build_updates_tab(self, tab: ttk.Frame) -> None:
        ttk.Label(tab, text="Paquete de actualización firmado", font=("Segoe UI", 12, "bold")).pack(
            anchor="w"
        )
        ttk.Label(tab, text="La actualización preserva licencia.key y configs del cliente.").pack(
            anchor="w", pady=(4, 14)
        )
        ttk.Button(tab, text="Generar update", style="Primary.TButton", command=self.generate_update).pack(
            anchor="w"
        )

    def selected_client_id(self) -> str | None:
        selection = self.tree.selection()
        return str(self.tree.item(selection[0], "values")[0]) if selection else None

    def refresh_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        rows: list[ClientRow] = []
        for cid, client in self.db.items():
            license_data = client.get("license") or {}
            expires = str(license_data.get("expires_at_utc") or "")
            status, days = license_status(expires)
            path = str(license_data.get("artifact_path") or "")
            rows.append(
                ClientRow(
                    cid,
                    str(client.get("name") or cid),
                    str(license_data.get("license_id") or ""),
                    expires,
                    status,
                    days,
                    path,
                )
            )
        for row in sorted(rows, key=lambda item: item.name.casefold()):
            self.tree.insert(
                "",
                "end",
                values=(
                    row.client_id,
                    row.name,
                    row.license_id,
                    row.expires_at,
                    row.status,
                    row.days_left,
                    row.license_path,
                ),
            )

    def create_client(self) -> None:
        dialog = NewClientDialog(self)
        self.wait_window(dialog)
        if not dialog.result:
            return
        name, duration = dialog.result
        cid = client_id_from_name(name)
        if cid in self.db:
            messagebox.showwarning("Cliente existente", "Ese cliente ya existe.")
            return
        issued = now_utc()
        client = {
            "client_id": cid,
            "name": name,
            "license": {
                "license_id": f"LIC-{uuid.uuid4().hex[:12].upper()}",
                "issued_at_utc": iso_z(issued),
                "expires_at_utc": iso_z(expiration_from_duration(duration, base=issued)),
                "status": "active",
                "duration": duration,
                "actions": [],
            },
            "build_history": [],
        }
        try:
            bundle = export_client_license_bundle(client)
            client["license"]["artifact_path"] = bundle["license_path"]
            client["license"]["public_key_path"] = bundle["public_key_path"]
            self.db[cid] = client
            save_db(self.db)
        except Exception as exc:
            messagebox.showerror("No se creó la licencia", str(exc))
            return
        self.refresh_table()
        messagebox.showinfo(
            "Cliente creado",
            f"Licencia firmada creada automáticamente:\n{bundle['license_path']}",
        )

    def renew_license(self) -> None:
        cid = self.selected_client_id()
        if not cid:
            messagebox.showinfo("Selecciona", "Selecciona un cliente primero.")
            return
        dialog = DurationDialog(self, "Renovar o extender", include_action=True)
        self.wait_window(dialog)
        if not dialog.result:
            return
        action, duration = dialog.result
        client = copy.deepcopy(self.db[cid])
        license_data = client.setdefault("license", {})
        now = now_utc()
        try:
            current_expiration = parse_dt(str(license_data.get("expires_at_utc") or ""))
        except Exception:
            current_expiration = now
        base = current_expiration if action == "extend" and current_expiration > now else now
        license_data["issued_at_utc"] = iso_z(now)
        license_data["expires_at_utc"] = iso_z(expiration_from_duration(duration, base=base))
        license_data["status"] = "active"
        license_data["duration"] = duration
        license_data.setdefault("actions", []).append(
            {"at_utc": iso_z(now), "action": action, "duration": duration}
        )
        try:
            bundle = export_client_license_bundle(client)
            license_data["artifact_path"] = bundle["license_path"]
            license_data["public_key_path"] = bundle["public_key_path"]
            self.db[cid] = client
            save_db(self.db)
        except Exception as exc:
            messagebox.showerror("No se renovó la licencia", str(exc))
            return
        self.refresh_table()
        messagebox.showinfo(
            "Licencia renovada",
            f"Archivo firmado reemplazado:\n{bundle['license_path']}",
        )

    def export_license(self) -> None:
        cid = self.selected_client_id()
        if not cid:
            messagebox.showinfo("Selecciona", "Selecciona un cliente primero.")
            return
        destination = filedialog.askdirectory(title="Exportar licencia y clave pública")
        if not destination:
            return
        try:
            bundle = export_client_license_bundle(self.db[cid], destination=destination)
        except Exception as exc:
            messagebox.showerror("Error al exportar", str(exc))
            return
        messagebox.showinfo(
            "Licencia exportada",
            f"Licencia:\n{bundle['license_path']}\n\nClave pública:\n{bundle['public_key_path']}",
        )

    def delete_client(self) -> None:
        cid = self.selected_client_id()
        if not cid:
            messagebox.showinfo("Selecciona", "Selecciona un cliente primero.")
            return
        if not messagebox.askyesno(
            "Confirmar",
            f"¿Eliminar el registro de {cid}?\nLos artefactos ya exportados no se borrarán.",
        ):
            return
        self.db.pop(cid, None)
        save_db(self.db)
        self.refresh_table()

    def generate_installer(self) -> None:
        cid = self.selected_client_id()
        if not cid:
            messagebox.showinfo("Selecciona", "Selecciona un cliente primero.")
            return
        destination = filedialog.askdirectory(title="Guardar instalador en...")
        if destination:
            self._run_long_task(
                "Generando instalador",
                lambda: make_installer_zip(self.db[cid], destination),
                lambda path: self._build_done(cid, path, "installer"),
            )

    def generate_update(self) -> None:
        destination = filedialog.askdirectory(title="Guardar actualización en...")
        if destination:
            self._run_long_task(
                "Generando actualización",
                lambda: make_update_zip(VERSION, destination),
                lambda path: messagebox.showinfo("Actualización generada", path),
            )

    def _build_done(self, cid: str, path: str, kind: str) -> None:
        self.db[cid].setdefault("build_history", []).append(
            {"built_at_utc": iso_z(now_utc()), "artifact": path, "type": kind}
        )
        save_db(self.db)
        messagebox.showinfo("Instalador generado", path)

    def _run_long_task(self, title: str, task, done) -> None:
        window = tk.Toplevel(self)
        window.title(title)
        window.transient(self)
        window.grab_set()
        ttk.Label(window, text=f"{title}. No cierres esta ventana.", padding=20).pack()

        def worker() -> None:
            try:
                result = task()
            except Exception as exc:
                error_message = str(exc)
                self.after(
                    0,
                    lambda message=error_message: (
                        window.destroy(),
                        messagebox.showerror(title, message),
                    ),
                )
                return
            self.after(0, lambda: (window.destroy(), done(result)))

        threading.Thread(target=worker, daemon=True).start()


def main() -> None:
    Dashboard().mainloop()


if __name__ == "__main__":
    main()
