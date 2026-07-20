import os
import re
import json
import uuid
import shutil
import zipfile
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    from dateutil.relativedelta import relativedelta
except Exception:
    relativedelta = None

APP_NAME = "DMS - Lector QR | Dashboard de Instaladores"
APP_VERSION = "2.0.0"

COLOR_BG = "#212121"
COLOR_TEXT = "white"
COLOR_ACCENT = "#e53935"
COLOR_PANEL = "#2a2a2a"
COLOR_INPUT = "#1e1e1e"


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CLIENTES_DIR = os.path.join(BASE_DIR, "clientes")
DB_PATH = os.path.join(CLIENTES_DIR, "db_clientes.json")

TEMPLATE_DIR = os.path.join(BASE_DIR, "template")
MAIN_SCRIPT = os.path.join(TEMPLATE_DIR, "main.py")
CONFIGURADOR_SCRIPT = os.path.join(TEMPLATE_DIR, "crear_configuracion.py")
LECTOR_OTRAS_SCRIPT = os.path.join(TEMPLATE_DIR, "lector_otras_cedulas.py")
CAPTURAR_FORMATO_SCRIPT = os.path.join(TEMPLATE_DIR, "capturar_nuevo_formato.py")
CONFIGS_SRC = os.path.join(TEMPLATE_DIR, "configs")
ASSETS_SRC = os.path.join(TEMPLATE_DIR, "assets")

UNITS = ["Horas", "Días", "Meses", "Años"]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_dt(s: str) -> datetime:
    # supports "...Z" or naive
    if not s:
        raise ValueError("empty datetime")
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def client_id_from_name(name: str) -> str:
    name = name.strip()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return slug.upper()[:40] or f"CLIENTE_{uuid.uuid4().hex[:6].upper()}"


def calcular_expiracion(valor: int, unidad: str, base: datetime | None = None) -> datetime:
    base = base or now_utc()
    if unidad == "Horas":
        return base + timedelta(hours=int(valor))
    if unidad == "Días":
        return base + timedelta(days=int(valor))

    # Exactitud real para meses/años
    if unidad in ("Meses", "Años"):
        if relativedelta is None:
            # fallback aproximado si falta python-dateutil
            days = 30 * int(valor) if unidad == "Meses" else 365 * int(valor)
            return base + timedelta(days=days)
        if unidad == "Meses":
            return base + relativedelta(months=int(valor))
        return base + relativedelta(years=int(valor))

    return base


def calcular_expiracion_comp(d: dict, base: datetime | None = None) -> datetime:
    """Duración compuesta: years + months (calendario) + days + hours."""
    base = base or now_utc()
    years = int(d.get("years", 0) or 0)
    months = int(d.get("months", 0) or 0)
    days = int(d.get("days", 0) or 0)
    hours = int(d.get("hours", 0) or 0)

    dt = base
    if years or months:
        if relativedelta is None:
            dt = dt + timedelta(days=(365 * years) + (30 * months))
        else:
            dt = dt + relativedelta(years=years, months=months)

    if days or hours:
        dt = dt + timedelta(days=days, hours=hours)

    return dt


def duracion_a_texto(d: dict) -> str:
    parts = []
    for k, label in (("years", "años"), ("months", "meses"), ("days", "días"), ("hours", "horas")):
        v = int(d.get(k, 0) or 0)
        if v:
            parts.append(f"{v} {label}")
    return " + ".join(parts) if parts else "0 días"


def load_db() -> dict:
    os.makedirs(CLIENTES_DIR, exist_ok=True)
    if not os.path.exists(DB_PATH):
        return {}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            # migración desde log viejo (si existe)
            migrated = {}
            for row in data:
                cid = client_id_from_name(row.get("cliente", ""))
                migrated[cid] = {
                    "client_id": cid,
                    "name": row.get("cliente", cid),
                    "license": {
                        "license_id": row.get("licencia"),
                        "issued_at_utc": row.get("fecha"),
                        "expires_at_utc": row.get("expira"),
                        "status": "active",
                    },
                    "build_history": [
                        {
                            "built_at_utc": iso_z(now_utc()),
                            "artifact": row.get("zip"),
                            "type": "installer",
                        }
                    ],
                }
            return migrated
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_db(db: dict) -> None:
    os.makedirs(CLIENTES_DIR, exist_ok=True)
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def license_status(expires_at_utc: str) -> tuple[str, int]:
    try:
        exp = parse_dt(expires_at_utc)
        diff = exp - now_utc()
        days_left = int(diff.total_seconds() // 86400)
        if diff.total_seconds() <= 0:
            return "EXPIRADA", days_left
        return "ACTIVA", days_left
    except Exception:
        return "DESCONOCIDA", 0


def ensure_template_structure():
    missing = []
    for p in [MAIN_SCRIPT, CONFIGURADOR_SCRIPT, LECTOR_OTRAS_SCRIPT, CAPTURAR_FORMATO_SCRIPT]:
        if not os.path.exists(p):
            missing.append(p)
    if missing:
        raise FileNotFoundError("Faltan archivos de template: \n" + "\n".join(missing))


def build_exes(workdir: str, icon_ico: str | None = None) -> tuple[str, str]:
    """Compila main.py y crear_configuracion.py con PyInstaller (Windows)."""
    pyinstaller = shutil.which("pyinstaller")
    if not pyinstaller:
        raise RuntimeError("No se encontró 'pyinstaller' en PATH. Instala con: pip install pyinstaller")

    exe_main_name = f"lector_qr_{uuid.uuid4().hex[:6]}"
    exe_cfg_name = "crear_configuracion"

    icon_arg = []
    if icon_ico and os.path.exists(os.path.join(workdir, icon_ico)):
        icon_arg = ["--icon", icon_ico]

    subprocess.run(
        [pyinstaller, "--onefile", "--noconsole", *icon_arg, "--name", exe_main_name, "main.py"],
        cwd=workdir,
        check=True,
    )
    subprocess.run(
        [pyinstaller, "--onefile", "--noconsole", *icon_arg, "--name", exe_cfg_name, "crear_configuracion.py"],
        cwd=workdir,
        check=True,
    )

    exe_main = os.path.join(workdir, "dist", f"{exe_main_name}.exe")
    exe_cfg = os.path.join(workdir, "dist", f"{exe_cfg_name}.exe")

    if not os.path.exists(exe_main) or not os.path.exists(exe_cfg):
        raise RuntimeError("PyInstaller no generó los ejecutables esperados.")

    return exe_main, exe_cfg


def zip_folder(folder: str, zip_path: str):
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(folder):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, folder)
                z.write(full, rel)


def _find_iscc() -> str | None:
    """Busca Inno Setup Compiler en Windows."""
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Inno Setup 6", "ISCC.exe"),
        shutil.which("ISCC.exe") or "",
        shutil.which("iscc") or "",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def _write_client_inno_script(build_root: str, client: dict, app_dir: str, out_dir: str, use_setup_icon: bool = True) -> str:
    """Crea el .iss específico del cliente para generar Setup.exe.

    use_setup_icon=True intenta poner el logo al Setup.exe.
    Si Inno/antivirus bloquea la actualización de recursos (error 110),
    el dashboard reintenta automáticamente con use_setup_icon=False.
    Los accesos directos y la app instalada conservan el logo igualmente.
    """
    icon_path = os.path.join(app_dir, "assets", "DMS_icono_circulo_i.ico")
    iss_path = os.path.join(build_root, "LectorCedulasDMS_cliente.iss")
    output_base = f"LectorCedulasDMS_Setup_{client['client_id']}_{now_utc().strftime('%Y%m%d_%H%M%S')}"

    def esc(path: str) -> str:
        return os.path.abspath(path).replace('\\', '\\\\')

    setup_icon_line = f"SetupIconFile={esc(icon_path)}" if use_setup_icon and os.path.exists(icon_path) else "; SetupIconFile omitido por compatibilidad"

    content = f"""
#define MyAppName "Lector Cédulas DMS"
#define MyAppVersion "4.0"
#define MyAppPublisher "Digital Management Systems"
#define MyAppExeName "LectorCedulasDMS.exe"

[Setup]
AppId={{{{DMS-LECTOR-CEDULAS-{client['client_id']}}}}}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
DefaultDirName={{autopf}}\\DMS\\LectorCedulasDMS
DefaultGroupName={{#MyAppName}}
DisableProgramGroupPage=yes
OutputDir={esc(out_dir)}
OutputBaseFilename={output_base}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
{setup_icon_line}
UninstallDisplayIcon={{app}}\\{{#MyAppExeName}}
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: checkedonce
Name: "startup"; Description: "Iniciar automáticamente con Windows"; GroupDescription: "Inicio automático:"; Flags: unchecked

[Files]
Source: "{esc(app_dir)}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; IconFilename: "{{app}}\\assets\\DMS_icono_circulo_i.ico"
Name: "{{autodesktop}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; Tasks: desktopicon; IconFilename: "{{app}}\\assets\\DMS_icono_circulo_i.ico"
Name: "{{userstartup}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; Tasks: startup; IconFilename: "{{app}}\\assets\\DMS_icono_circulo_i.ico"
Name: "{{group}}\\Configurar lector"; Filename: "{{app}}\\crear_configuracion.exe"; IconFilename: "{{app}}\\assets\\DMS_icono_circulo_i.ico"

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Description: "Ejecutar {{#MyAppName}}"; Flags: nowait postinstall skipifsilent
""".strip()
    with open(iss_path, "w", encoding="utf-8") as f:
        f.write(content)
    return iss_path



def _run_inno_with_retry(iscc: str, build_root: str, client: dict, app_dir: str, out_dir: str) -> str:
    """Compila con Inno Setup. Si falla al aplicar icono al Setup.exe, reintenta sin SetupIconFile."""
    import subprocess

    iss_path = _write_client_inno_script(build_root, client, app_dir, out_dir, use_setup_icon=True)
    try:
        subprocess.run([iscc, iss_path], cwd=build_root, check=True)
        return iss_path
    except subprocess.CalledProcessError as err:
        # Error típico de Inno: EndUpdateResource failed (110) al actualizar el icono del Setup.exe.
        # Reintentar sin SetupIconFile permite generar el instalador; la app y accesos directos mantienen logo.
        guardar_msg = (
            "Inno Setup falló al aplicar el icono al Setup.exe. "
            "Reintentando sin SetupIconFile. La aplicación instalada conservará el logo.\n"
            f"Detalle: {err}"
        )
        try:
            print(guardar_msg)
        except Exception:
            pass
        iss_path = _write_client_inno_script(build_root, client, app_dir, out_dir, use_setup_icon=False)
        subprocess.run([iscc, iss_path], cwd=build_root, check=True)
        return iss_path

def make_installer_zip(client: dict, out_dir: str) -> str:
    """Genera un INSTALADOR Setup.exe para el cliente usando PyInstaller + Inno Setup."""
    ensure_template_structure()

    iscc = _find_iscc()
    if not iscc:
        raise RuntimeError(
            "No se encontró Inno Setup 6 (ISCC.exe). Instálalo desde https://jrsoftware.org/isdl.php "
            "y vuelve a generar el instalador."
        )

    ts = now_utc().strftime("%Y%m%d_%H%M%S")
    base_name = f"{client['client_id']}_{ts}"
    build_root = os.path.join(CLIENTES_DIR, "_build", base_name)
    os.makedirs(build_root, exist_ok=True)

    workdir = os.path.join(build_root, "work")
    os.makedirs(workdir, exist_ok=True)

    shutil.copy2(MAIN_SCRIPT, os.path.join(workdir, "main.py"))
    shutil.copy2(CONFIGURADOR_SCRIPT, os.path.join(workdir, "crear_configuracion.py"))
    shutil.copy2(LECTOR_OTRAS_SCRIPT, os.path.join(workdir, "lector_otras_cedulas.py"))
    shutil.copy2(CAPTURAR_FORMATO_SCRIPT, os.path.join(workdir, "capturar_nuevo_formato.py"))

    if os.path.exists(CONFIGS_SRC):
        shutil.copytree(CONFIGS_SRC, os.path.join(workdir, "configs"), dirs_exist_ok=True)
    else:
        os.makedirs(os.path.join(workdir, "configs"), exist_ok=True)

    if os.path.exists(ASSETS_SRC):
        shutil.copytree(ASSETS_SRC, os.path.join(workdir, "assets"), dirs_exist_ok=True)

    lic_payload = {
        "licencia": client["license"]["license_id"],
        "expira": client["license"]["expires_at_utc"],
        "issued_at_utc": client["license"].get("issued_at_utc"),
        "client_id": client["client_id"],
        "schema": "dms_license_v2",
    }
    with open(os.path.join(workdir, "licencia.key"), "w", encoding="utf-8") as f:
        json.dump(lic_payload, f, indent=2, ensure_ascii=False)

    icon_rel = os.path.join("assets", "DMS_icono_circulo_i.ico")
    exe_main, exe_cfg = build_exes(workdir, icon_ico=icon_rel)

    app_dir = os.path.join(build_root, "app")
    os.makedirs(app_dir, exist_ok=True)
    shutil.copy2(exe_main, os.path.join(app_dir, "LectorCedulasDMS.exe"))
    shutil.copy2(exe_cfg, os.path.join(app_dir, "crear_configuracion.exe"))
    shutil.copy2(os.path.join(workdir, "lector_otras_cedulas.py"), os.path.join(app_dir, "lector_otras_cedulas.py"))
    shutil.copy2(os.path.join(workdir, "capturar_nuevo_formato.py"), os.path.join(app_dir, "capturar_nuevo_formato.py"))
    shutil.copy2(os.path.join(workdir, "licencia.key"), os.path.join(app_dir, "licencia.key"))

    if os.path.exists(os.path.join(workdir, "configs")):
        shutil.copytree(os.path.join(workdir, "configs"), os.path.join(app_dir, "configs"), dirs_exist_ok=True)
    if os.path.exists(os.path.join(workdir, "assets")):
        shutil.copytree(os.path.join(workdir, "assets"), os.path.join(app_dir, "assets"), dirs_exist_ok=True)

    iss_path = _run_inno_with_retry(iscc, build_root, client, app_dir, out_dir)

    setups = [os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.lower().endswith(".exe") and client["client_id"].lower() in f.lower()]
    if not setups:
        raise RuntimeError("Inno Setup terminó, pero no se encontró el Setup.exe generado.")
    setup_path = max(setups, key=os.path.getmtime)

    try:
        shutil.copy2(iss_path, os.path.join(out_dir, os.path.splitext(os.path.basename(setup_path))[0] + ".iss"))
    except Exception:
        pass

    return setup_path


def make_update_zip(version: str, out_dir: str) -> str:
    """Genera ZIP de actualización (updater + app build)."""
    ensure_template_structure()

    ts = now_utc().strftime("%Y%m%d_%H%M%S")
    base_name = f"UPDATE_{version}_{ts}"

    build_root = os.path.join(CLIENTES_DIR, "_build", base_name)
    os.makedirs(build_root, exist_ok=True)

    # Compilar app dentro de build_root/app
    app_dir = os.path.join(build_root, "app")
    os.makedirs(app_dir, exist_ok=True)

    shutil.copy2(MAIN_SCRIPT, os.path.join(app_dir, "main.py"))
    shutil.copy2(CONFIGURADOR_SCRIPT, os.path.join(app_dir, "crear_configuracion.py"))
    shutil.copy2(LECTOR_OTRAS_SCRIPT, os.path.join(app_dir, "lector_otras_cedulas.py"))
    shutil.copy2(CAPTURAR_FORMATO_SCRIPT, os.path.join(app_dir, "capturar_nuevo_formato.py"))

    if os.path.exists(ASSETS_SRC):
        shutil.copytree(ASSETS_SRC, os.path.join(app_dir, "assets"), dirs_exist_ok=True)

    icon_rel = os.path.join("assets", "DMS_icono_circulo_i.ico")
    exe_main, exe_cfg = build_exes(app_dir, icon_ico=icon_rel)

    # Construir paquete update
    update_dir = os.path.join(build_root, "update")
    os.makedirs(update_dir, exist_ok=True)

    # updater
    updater_src = os.path.join(BASE_DIR, "tools", "updater.py")
    shutil.copy2(updater_src, os.path.join(update_dir, "updater.py"))

    # app payload (solo binarios + assets)
    payload_dir = os.path.join(update_dir, "app")
    os.makedirs(payload_dir, exist_ok=True)
    shutil.copy2(exe_main, os.path.join(payload_dir, os.path.basename(exe_main)))
    shutil.copy2(exe_cfg, os.path.join(payload_dir, os.path.basename(exe_cfg)))
    shutil.copy2(os.path.join(app_dir, "lector_otras_cedulas.py"), os.path.join(payload_dir, "lector_otras_cedulas.py"))
    shutil.copy2(os.path.join(app_dir, "capturar_nuevo_formato.py"), os.path.join(payload_dir, "capturar_nuevo_formato.py"))

    assets_src = os.path.join(app_dir, "assets")
    if os.path.exists(assets_src):
        shutil.copytree(assets_src, os.path.join(payload_dir, "assets"), dirs_exist_ok=True)

    manifest = {
        "product": "DMS Lector QR",
        "version": version,
        "built_at_utc": iso_z(now_utc()),
        "notes": "Update sin instalador externo. Preserva licencia y configs.",
    }
    with open(os.path.join(update_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    zip_path = os.path.join(out_dir, f"{base_name}.zip")
    os.makedirs(out_dir, exist_ok=True)
    zip_folder(update_dir, zip_path)

    # Cleanup heavy
    shutil.rmtree(os.path.join(app_dir, "build"), ignore_errors=True)
    shutil.rmtree(os.path.join(app_dir, "dist"), ignore_errors=True)

    return zip_path


@dataclass
class ClientRow:
    client_id: str
    name: str
    license_id: str
    expires_at: str
    status: str
    days_left: int
    last_build: str


class Dashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("980x620")
        self.minsize(920, 580)
        self.configure(bg=COLOR_BG)
        self._apply_window_icon()

        self.db = load_db()

        self._build_style()
        self._build_ui()
        self.refresh_table()

        if relativedelta is None:
            self.after(300, lambda: messagebox.showwarning(
                "Dependencia faltante",
                "Para fechas exactas (Meses/Años) instalá: pip install python-dateutil\n"
                "Por ahora se usará un cálculo aproximado para Meses/Años."
            ))

    def _apply_window_icon(self):
        icon_path = os.path.join(ASSETS_SRC, "DMS_icono_circulo_i.ico")
        try:
            if os.path.exists(icon_path):
                self.iconbitmap(default=icon_path)
        except Exception:
            pass

    def _build_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("App.TFrame", background=COLOR_BG)
        style.configure("Header.TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=("Segoe UI", 18, "bold"))
        style.configure("Sub.TLabel", background=COLOR_BG, foreground="#cfcfcf", font=("Segoe UI", 10))

        style.configure("TNotebook", background=COLOR_BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI", 10, "bold"))

        style.configure(
            "Primary.TButton",
            background=COLOR_ACCENT,
            foreground="white",
            font=("Segoe UI", 10, "bold"),
            padding=8,
        )
        style.map("Primary.TButton", background=[("active", "#c62828")])

        style.configure(
            "Ghost.TButton",
            background=COLOR_PANEL,
            foreground=COLOR_TEXT,
            font=("Segoe UI", 10),
            padding=8,
        )
        style.map("Ghost.TButton", background=[("active", "#333333")])

        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("TEntry", fieldbackground=COLOR_INPUT, foreground=COLOR_TEXT)
        style.configure("TCombobox", fieldbackground=COLOR_INPUT, foreground=COLOR_TEXT)

        style.configure(
            "Treeview",
            background="#1a1a1a",
            fieldbackground="#1a1a1a",
            foreground=COLOR_TEXT,
            rowheight=28,
        )
        style.configure(
            "Treeview.Heading",
            background=COLOR_PANEL,
            foreground=COLOR_TEXT,
            font=("Segoe UI", 10, "bold"),
        )
        style.map("Treeview", background=[("selected", "#3b0f0f")])

    def _build_ui(self):
        root = ttk.Frame(self, style="App.TFrame", padding=16)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root, style="App.TFrame")
        header.pack(fill="x")

        
        logo_path = os.path.join(ASSETS_SRC, "DMS_icono_circulo_i.ico")
        try:
            from PIL import Image, ImageTk
            if os.path.exists(logo_path):
                img = Image.open(logo_path).resize((48, 48))
                self._header_logo = ImageTk.PhotoImage(img)
                ttk.Label(header, image=self._header_logo, background=COLOR_BG).pack(side="left", padx=(0, 12))
        except Exception:
            pass
        title_box = ttk.Frame(header, style="App.TFrame")
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="DMS Lector QR", style="Header.TLabel").pack(anchor="w")
        ttk.Label(title_box, text=f"Dashboard de Instaladores • v{APP_VERSION} • DB: {os.path.relpath(DB_PATH, BASE_DIR)}", style="Sub.TLabel").pack(anchor="w", pady=(2, 12))

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True)

        self.tab_clients = ttk.Frame(self.nb, style="App.TFrame")
        self.tab_generate = ttk.Frame(self.nb, style="App.TFrame")
        self.tab_updates = ttk.Frame(self.nb, style="App.TFrame")
        self.tab_help = ttk.Frame(self.nb, style="App.TFrame")

        self.nb.add(self.tab_clients, text="Clientes")
        self.nb.add(self.tab_generate, text="Generar")
        self.nb.add(self.tab_updates, text="Updates")
        self.nb.add(self.tab_help, text="Ayuda")

        self._build_clients_tab()
        self._build_generate_tab()
        self._build_updates_tab()
        self._build_help_tab()

    # -------- Clientes --------
    def _build_clients_tab(self):
        top = ttk.Frame(self.tab_clients, style="App.TFrame")
        top.pack(fill="x", pady=(0, 10))

        ttk.Button(top, text="➕ Nuevo", style="Primary.TButton", command=self.create_client).pack(side="left")
        ttk.Button(top, text="✏️ Editar", style="Ghost.TButton", command=self.edit_client).pack(side="left", padx=8)
        ttk.Button(top, text="🗑 Eliminar", style="Ghost.TButton", command=self.delete_client).pack(side="left")

        ttk.Button(top, text="📦 Re-emitir instalador", style="Primary.TButton", command=self.reemit_installer).pack(side="right")
        ttk.Button(top, text="♻️ Renovar/Extender", style="Ghost.TButton", command=self.renew_license).pack(side="right", padx=8)

        table_frame = ttk.Frame(self.tab_clients, style="App.TFrame")
        table_frame.pack(fill="both", expand=True)

        cols = ("client_id", "name", "license_id", "expires", "status", "days", "last_build")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        self.tree.heading("client_id", text="Client ID")
        self.tree.heading("name", text="Cliente")
        self.tree.heading("license_id", text="Licencia")
        self.tree.heading("expires", text="Expira (UTC)")
        self.tree.heading("status", text="Estado")
        self.tree.heading("days", text="Días")
        self.tree.heading("last_build", text="Último build")

        self.tree.column("client_id", width=120)
        self.tree.column("name", width=240)
        self.tree.column("license_id", width=140)
        self.tree.column("expires", width=190)
        self.tree.column("status", width=90)
        self.tree.column("days", width=60, anchor="e")
        self.tree.column("last_build", width=200)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        bottom = ttk.Frame(self.tab_clients, style="App.TFrame")
        bottom.pack(fill="x", pady=(10, 0))

        ttk.Button(bottom, text="🔄 Refrescar", style="Ghost.TButton", command=self.refresh_table).pack(side="left")
        ttk.Button(bottom, text="📂 Abrir carpeta clientes", style="Ghost.TButton", command=self.open_clients_folder).pack(side="left", padx=8)

    def _selected_client_id(self) -> str | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.item(sel[0], "values")[0]

    def refresh_table(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

        rows = []
        for cid, c in self.db.items():
            lic = c.get("license", {})
            license_id = lic.get("license_id", "")
            expires = lic.get("expires_at_utc", "")
            status, days = license_status(expires)
            last_build = ""
            hist = c.get("build_history", [])
            if hist:
                last_build = hist[-1].get("artifact", "")
            rows.append(ClientRow(cid, c.get("name", cid), license_id, expires, status, days, last_build))

        rows.sort(key=lambda r: (r.status != "ACTIVA", r.name.lower()))

        for r in rows:
            self.tree.insert("", "end", values=(r.client_id, r.name, r.license_id, r.expires_at, r.status, r.days_left, r.last_build))

        save_db(self.db)
        try:
            self._refresh_generate_clients()
        except Exception:
            pass

    def open_clients_folder(self):
        os.makedirs(CLIENTES_DIR, exist_ok=True)
        try:
            os.startfile(CLIENTES_DIR)  # type: ignore
        except Exception:
            messagebox.showinfo("Ruta", CLIENTES_DIR)

    # -------- CRUD --------
    def create_client(self):
        dlg = ClientDialog(self, title="Nuevo cliente")
        self.wait_window(dlg)
        if not dlg.result:
            return

        name, duration = dlg.result
        cid = client_id_from_name(name)
        if cid in self.db:
            messagebox.showwarning("Existe", "Ya existe un cliente con ese ID. Usa Editar.")
            return

        issued = now_utc()
        expires = calcular_expiracion_comp(duration, base=issued)

        self.db[cid] = {
            "client_id": cid,
            "name": name,
            "license": {
                "license_id": f"LIC-{uuid.uuid4().hex[:8].upper()}",
                "issued_at_utc": iso_z(issued),
                "expires_at_utc": iso_z(expires),
                "status": "active",
            "duration": duration,
            },
            "build_history": [],
        }
        save_db(self.db)
        self.refresh_table()

    def edit_client(self):
        cid = self._selected_client_id()
        if not cid:
            messagebox.showinfo("Selecciona", "Selecciona un cliente primero.")
            return

        c = self.db.get(cid)
        if not c:
            return

        dlg = EditClientDialog(self, title="Editar cliente", name=c.get("name", cid))
        self.wait_window(dlg)
        if not dlg.result:
            return

        new_name = dlg.result
        c["name"] = new_name
        save_db(self.db)
        self.refresh_table()

    def delete_client(self):
        cid = self._selected_client_id()
        if not cid:
            messagebox.showinfo("Selecciona", "Selecciona un cliente primero.")
            return

        c = self.db.get(cid)
        if not c:
            return

        if not messagebox.askyesno("Confirmar", f"¿Eliminar '{c.get('name', cid)}' y su licencia?\n\nEsto NO borra zips ya generados."):
            return

        self.db.pop(cid, None)
        save_db(self.db)
        self.refresh_table()

    # -------- Licencias / Builds --------
    def reemit_installer(self):
        cid = self._selected_client_id()
        if not cid:
            messagebox.showinfo("Selecciona", "Selecciona un cliente primero.")
            return

        out_dir = filedialog.askdirectory(title="Guardar instalador en...")
        if not out_dir:
            return

        client = self.db[cid]
        self._run_long_task(
            title="Generando instalador",
            fn=lambda: make_installer_zip(client, out_dir),
            on_done=lambda zip_path: self._after_build(cid, zip_path, kind="installer"),
        )
    def renew_license(self):
        cid = self._selected_client_id()
        if not cid:
            messagebox.showinfo("Selecciona", "Selecciona un cliente primero.")
            return

        c = self.db.get(cid)
        if not c:
            return

        dlg = RenewDialog(self, title="Licencia: renovar o extender")
        self.wait_window(dlg)
        if not dlg.result:
            return

        action, duration = dlg.result  # "extend" | "renew"
        lic = c.get("license", {})

        try:
            current_exp = parse_dt(lic.get("expires_at_utc", ""))
        except Exception:
            current_exp = now_utc()

        base = now_utc()
        if action == "extend":
            # Si todavía está activa, extender desde la expiración actual; si no, desde hoy
            if current_exp and current_exp > base:
                base = current_exp
        elif action == "renew":
            # Renovar reinicia desde hoy
            base = now_utc()

        new_exp = calcular_expiracion_comp(duration, base=base)

        lic["expires_at_utc"] = iso_z(new_exp)
        lic["status"] = "active"
        lic["duration"] = duration
        lic.setdefault("actions", []).append(
            {
                "at_utc": iso_z(now_utc()),
                "action": action,
                "duration": duration,
                "new_expires_at_utc": lic["expires_at_utc"],
            }
        )

        c["license"] = lic
        save_db(self.db)
        self.refresh_table()
        messagebox.showinfo("Listo", f"Nueva expiración (UTC):\n{lic['expires_at_utc']}")

    def _after_build(self, cid: str, zip_path: str, kind: str):
        c = self.db.get(cid)
        if c is not None:
            c.setdefault("build_history", []).append({
                "built_at_utc": iso_z(now_utc()),
                "artifact": zip_path,
                "type": kind,
            })
            save_db(self.db)
        self.refresh_table()
        messagebox.showinfo("Listo", f"Instalador generado:\n{zip_path}")
        try:
            os.startfile(os.path.dirname(zip_path))  # type: ignore
        except Exception:
            pass
    # -------- Generar Tab --------
    def _build_generate_tab(self):
        frame = ttk.Frame(self.tab_generate, style="App.TFrame", padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Generar instalador Setup.exe para un cliente",
            font=("Segoe UI", 12, "bold"),
            background=COLOR_BG,
            foreground=COLOR_TEXT,
        ).pack(anchor="w")

        ttk.Label(
            frame,
            text="Selecciona un cliente y genera el ZIP. Esto re-emite la licencia (con el tiempo transcurrido ya descontado).",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 14))

        card = ttk.Frame(frame, style="App.TFrame")
        card.pack(fill="x")

        ttk.Label(card, text="Cliente", background=COLOR_BG, foreground=COLOR_TEXT).grid(row=0, column=0, sticky="w")
        self.g_client = ttk.Combobox(card, state="readonly", width=56)
        self.g_client.grid(row=1, column=0, sticky="w", pady=(2, 10))

        ttk.Button(
            card,
            text="📦 Generar instalador",
            style="Primary.TButton",
            command=self.generate_for_selected_client,
        ).grid(row=1, column=1, sticky="w", padx=10)

        ttk.Separator(frame).pack(fill="x", pady=18)

        ttk.Label(
            frame,
            text="Generación rápida (crear cliente + generar ZIP)",
            font=("Segoe UI", 12, "bold"),
            background=COLOR_BG,
            foreground=COLOR_TEXT,
        ).pack(anchor="w")

        quick = ttk.Frame(frame, style="App.TFrame")
        quick.pack(fill="x", pady=(10, 0))

        ttk.Label(quick, text="Nombre cliente").grid(row=0, column=0, sticky="w")
        self.q_name = ttk.Entry(quick, width=40)
        self.q_name.grid(row=1, column=0, sticky="w", pady=(2, 10))

        dur = ttk.LabelFrame(quick, text="Duración (combinada)", padding=10)
        dur.grid(row=1, column=1, sticky="w", padx=14)

        self.q_years = tk.Spinbox(dur, from_=0, to=30, width=5)
        self.q_months = tk.Spinbox(dur, from_=0, to=24, width=5)
        self.q_days = tk.Spinbox(dur, from_=0, to=3650, width=6)
        self.q_hours = tk.Spinbox(dur, from_=0, to=87600, width=6)

        ttk.Label(dur, text="Años").grid(row=0, column=0, sticky="w")
        ttk.Label(dur, text="Meses").grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(dur, text="Días").grid(row=0, column=2, sticky="w", padx=(10, 0))
        ttk.Label(dur, text="Horas").grid(row=0, column=3, sticky="w", padx=(10, 0))

        self.q_years.grid(row=1, column=0, sticky="w")
        self.q_months.grid(row=1, column=1, sticky="w", padx=(10, 0))
        self.q_days.grid(row=1, column=2, sticky="w", padx=(10, 0))
        self.q_hours.grid(row=1, column=3, sticky="w", padx=(10, 0))

        # Default: 1 año
        self.q_years.delete(0, "end")
        self.q_years.insert(0, "1")

        ttk.Button(
            quick,
            text="Crear + Generar instalador",
            style="Primary.TButton",
            command=self.quick_create_and_build,
        ).grid(row=1, column=2, sticky="w")

        self._refresh_generate_clients()

    def _refresh_generate_clients(self):
        items = []
        for cid, c in sorted(self.db.items(), key=lambda x: (x[1].get("name","").lower(), x[0])):
            name = c.get("name", cid)
            items.append(f"{name} ({cid})")
        self.g_client["values"] = items
        if items and not self.g_client.get():
            self.g_client.current(0)

    def _selected_generate_cid(self) -> str | None:
        val = (self.g_client.get() or "").strip()
        if not val:
            return None
        m = re.search(r"\(([^()]+)\)\s*$", val)
        return m.group(1).strip() if m else None

    def generate_for_selected_client(self):
        cid = self._selected_generate_cid()
        if not cid:
            messagebox.showinfo("Selecciona", "Selecciona un cliente primero.")
            return
        if cid not in self.db:
            messagebox.showwarning("No existe", "El cliente seleccionado no existe en la base.")
            return

        out_dir = filedialog.askdirectory(title="Guardar instalador en...")
        if not out_dir:
            return

        client = self.db[cid]
        self._run_long_task(
            title="Generando instalador",
            fn=lambda: make_installer_zip(client, out_dir),
            on_done=lambda zip_path: self._after_build(cid, zip_path, kind="installer"),
        )

    def quick_create_and_build(self):
        name = self.q_name.get().strip()

        def _get(sp) -> int:
            try:
                return int(str(sp.get()).strip() or "0")
            except Exception:
                return 0

        duration = {
            "years": _get(self.q_years),
            "months": _get(self.q_months),
            "days": _get(self.q_days),
            "hours": _get(self.q_hours),
        }

        if not name:
            messagebox.showwarning("Campos", "Ingresa el nombre del cliente.")
            return
        if all(int(v) == 0 for v in duration.values()):
            messagebox.showwarning("Campos", "Define una duración (al menos 1 unidad).")
            return

        cid = client_id_from_name(name)
        if cid not in self.db:
            issued = now_utc()
            expires = calcular_expiracion_comp(duration, base=issued)
            self.db[cid] = {
                "client_id": cid,
                "name": name,
                "license": {
                    "license_id": f"LIC-{uuid.uuid4().hex[:8].upper()}",
                    "issued_at_utc": iso_z(issued),
                    "expires_at_utc": iso_z(expires),
                    "status": "active",
                    "duration": duration,
                },
                "build_history": [],
            }
            save_db(self.db)
            self.refresh_table()

        out_dir = filedialog.askdirectory(title="Guardar instalador en...")
        if not out_dir:
            return

        client = self.db[cid]
        self._run_long_task(
            title="Generando instalador",
            fn=lambda: make_installer_zip(client, out_dir),
            on_done=lambda zip_path: self._after_build(cid, zip_path, kind="installer"),
        )

        self._refresh_generate_clients()


    # -------- Updates Tab --------

    # -------- Updates Tab --------
    def _build_updates_tab(self):
        frame = ttk.Frame(self.tab_updates, style="App.TFrame", padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Updates (sin instalador externo)", font=("Segoe UI", 12, "bold"), background=COLOR_BG).pack(anchor="w")
        ttk.Label(frame, text="Genera un ZIP con updater.py + binarios. El usuario lo aplica sobre su carpeta instalada.", style="Sub.TLabel").pack(anchor="w", pady=(4, 14))

        form = ttk.Frame(frame, style="App.TFrame")
        form.pack(anchor="w")

        ttk.Label(form, text="Versión del update (ej: 2.0.1)").grid(row=0, column=0, sticky="w")
        self.u_ver = ttk.Entry(form, width=16)
        self.u_ver.insert(0, APP_VERSION)
        self.u_ver.grid(row=1, column=0, sticky="w", pady=(2, 10))

        ttk.Button(form, text="Generar instalador de Update", style="Primary.TButton", command=self.generate_update_zip).grid(row=1, column=1, sticky="w", padx=10)

        guide = (
            "Cómo aplicar en el cliente:\n"
            "1) Descomprimir el ZIP de update\n"
            "2) Abrir CMD en la carpeta del update\n"
            "3) Ejecutar: python updater.py --source .\\app --target C:\\Ruta\\Instalacion\n"
            "   (preserva licencia.key y configs)\n"
        )
        ttk.Label(frame, text=guide, background=COLOR_BG, foreground="#e5e5e5").pack(anchor="w", pady=(18, 0))

    def generate_update_zip(self):
        ver = self.u_ver.get().strip() or APP_VERSION
        out_dir = filedialog.askdirectory(title="Guardar ZIP de update en...")
        if not out_dir:
            return

        self._run_long_task(
            title="Generando update",
            fn=lambda: make_update_zip(ver, out_dir),
            on_done=lambda zip_path: messagebox.showinfo("Listo", f"Update Instalador generado:\n{zip_path}"),
        )

    # -------- Help Tab --------
    def _build_help_tab(self):
        frame = ttk.Frame(self.tab_help, style="App.TFrame", padding=14)
        frame.pack(fill="both", expand=True)

        text = (
            "Flujo recomendado:\n"
            "1) Clientes → Nuevo (creas el cliente y la licencia exacta)\n"
            "2) Clientes → Re-emitir instalador (genera Setup.exe con EXE + licencia + configs)\n"
            "3) En el cliente, descomprimir ZIP y ejecutar el EXE\n\n"
            "Seguimiento de licencias:\n"
            "- La consola guarda una DB (clientes/db_clientes.json) con la licencia y expiración en UTC\n"
            "- Re-emitir instalador vuelve a empacar la MISMA licencia (con el tiempo transcurrido ya descontado)\n\n"
            "Updates (sin instalador):\n"
            "- Updates → Generar instalador\n"
            "- En cliente: python updater.py --source .\\app --target <carpeta donde está instalado>\n"
            "- Preserva licencia.key y configs\n"
        )

        box = tk.Text(frame, wrap="word", height=22, bg="#101010", fg="#eaeaea", insertbackground="white", relief="flat")
        box.insert("1.0", text)
        box.config(state="disabled")
        box.pack(fill="both", expand=True)

    # -------- Utils --------
    def _run_long_task(self, title: str, fn, on_done):
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=COLOR_BG)
        win.resizable(False, False)
        ttk.Label(win, text=title + "...", background=COLOR_BG, foreground="white", font=("Segoe UI", 11, "bold")).pack(padx=18, pady=(16, 6))
        pb = ttk.Progressbar(win, mode="indeterminate")
        pb.pack(fill="x", padx=18, pady=(0, 16))
        pb.start(10)
        win.grab_set()

        def runner():
            try:
                result = fn()
                self.after(0, lambda r=result: (win.destroy(), on_done(r)))
            except Exception as err:
                mensaje = str(err)

                def mostrar_error(m=mensaje):
                    try:
                        win.destroy()
                    except Exception:
                        pass
                    messagebox.showerror("Error", m)

                self.after(0, mostrar_error)

        threading.Thread(target=runner, daemon=True).start()


class ClientDialog(tk.Toplevel):
    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=COLOR_BG)
        self.resizable(False, False)
        self.result = None

        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Nombre del cliente").grid(row=0, column=0, sticky="w")
        self.e_name = ttk.Entry(frm, width=46)
        self.e_name.grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 10))

        lf = ttk.LabelFrame(frm, text="Duración (combinada)", padding=10)
        lf.grid(row=2, column=0, columnspan=4, sticky="w")

        self.y = tk.Spinbox(lf, from_=0, to=30, width=6)
        self.m = tk.Spinbox(lf, from_=0, to=24, width=6)
        self.d = tk.Spinbox(lf, from_=0, to=3650, width=7)
        self.h = tk.Spinbox(lf, from_=0, to=87600, width=7)

        ttk.Label(lf, text="Años").grid(row=0, column=0, sticky="w")
        ttk.Label(lf, text="Meses").grid(row=0, column=1, sticky="w", padx=(10,0))
        ttk.Label(lf, text="Días").grid(row=0, column=2, sticky="w", padx=(10,0))
        ttk.Label(lf, text="Horas").grid(row=0, column=3, sticky="w", padx=(10,0))

        self.y.grid(row=1, column=0, sticky="w")
        self.m.grid(row=1, column=1, sticky="w", padx=(10,0))
        self.d.grid(row=1, column=2, sticky="w", padx=(10,0))
        self.h.grid(row=1, column=3, sticky="w", padx=(10,0))

        self.y.delete(0, "end")
        self.y.insert(0, "1")

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=4, sticky="e", pady=(12,0))
        ttk.Button(btns, text="Cancelar", style="Ghost.TButton", command=self.destroy).pack(side="right", padx=8)
        ttk.Button(btns, text="Crear", style="Primary.TButton", command=self._ok).pack(side="right")

        self.e_name.focus_set()

    def _ok(self):
        name = self.e_name.get().strip()

        def _get(sp):
            try:
                return int(str(sp.get()).strip() or "0")
            except Exception:
                return 0

        duration = {"years": _get(self.y), "months": _get(self.m), "days": _get(self.d), "hours": _get(self.h)}

        if not name:
            messagebox.showwarning("Campos", "Nombre requerido.")
            return
        if all(int(v) == 0 for v in duration.values()):
            messagebox.showwarning("Campos", "Define una duración (al menos 1 unidad).")
            return

        self.result = (name, duration)
        self.destroy()


class EditClientDialog(tk.Toplevel):
    def __init__(self, parent, title: str, name: str):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=COLOR_BG)
        self.resizable(False, False)
        self.result = None

        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Nombre del cliente").pack(anchor="w")
        self.e_name = ttk.Entry(frm, width=44)
        self.e_name.insert(0, name)
        self.e_name.pack(anchor="w", pady=(2, 10))

        btns = ttk.Frame(frm)
        btns.pack(anchor="e")
        ttk.Button(btns, text="Cancelar", style="Ghost.TButton", command=self.destroy).pack(side="right", padx=8)
        ttk.Button(btns, text="Guardar", style="Primary.TButton", command=self._ok).pack(side="right")

        self.e_name.focus_set()

    def _ok(self):
        name = self.e_name.get().strip()
        if not name:
            messagebox.showwarning("Campos", "Nombre requerido.")
            return
        self.result = name
        self.destroy()


class RenewDialog(tk.Toplevel):
    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=COLOR_BG)
        self.resizable(False, False)
        self.result = None

        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Acción").grid(row=0, column=0, sticky="w")
        self.action = tk.StringVar(value="extend")
        ttk.Radiobutton(frm, text="Extender (suma al vencimiento si está activa)", value="extend", variable=self.action).grid(row=1, column=0, sticky="w", pady=(2,0))
        ttk.Radiobutton(frm, text="Renovar (nuevo período desde hoy)", value="renew", variable=self.action).grid(row=2, column=0, sticky="w", pady=(2,10))

        lf = ttk.LabelFrame(frm, text="Duración (combinada)", padding=10)
        lf.grid(row=3, column=0, sticky="w")

        self.y = tk.Spinbox(lf, from_=0, to=30, width=6)
        self.m = tk.Spinbox(lf, from_=0, to=24, width=6)
        self.d = tk.Spinbox(lf, from_=0, to=3650, width=7)
        self.h = tk.Spinbox(lf, from_=0, to=87600, width=7)

        ttk.Label(lf, text="Años").grid(row=0, column=0, sticky="w")
        ttk.Label(lf, text="Meses").grid(row=0, column=1, sticky="w", padx=(10,0))
        ttk.Label(lf, text="Días").grid(row=0, column=2, sticky="w", padx=(10,0))
        ttk.Label(lf, text="Horas").grid(row=0, column=3, sticky="w", padx=(10,0))

        self.y.grid(row=1, column=0, sticky="w")
        self.m.grid(row=1, column=1, sticky="w", padx=(10,0))
        self.d.grid(row=1, column=2, sticky="w", padx=(10,0))
        self.h.grid(row=1, column=3, sticky="w", padx=(10,0))

        self.y.delete(0, "end")
        self.y.insert(0, "1")

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, sticky="e", pady=(12,0))
        ttk.Button(btns, text="Cancelar", style="Ghost.TButton", command=self.destroy).pack(side="right", padx=8)
        ttk.Button(btns, text="Aplicar", style="Primary.TButton", command=self._ok).pack(side="right")

    def _ok(self):
        def _get(sp):
            try:
                return int(str(sp.get()).strip() or "0")
            except Exception:
                return 0

        duration = {"years": _get(self.y), "months": _get(self.m), "days": _get(self.d), "hours": _get(self.h)}
        if all(int(v) == 0 for v in duration.values()):
            messagebox.showwarning("Campos", "Define una duración (al menos 1 unidad).")
            return
        self.result = (self.action.get(), duration)
        self.destroy()



def main():
    app = Dashboard()
    app.mainloop()


if __name__ == "__main__":
    main()
