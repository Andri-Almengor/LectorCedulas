import os
import sys
import json
import ctypes
import serial
import time
import threading
import pyautogui
import serial.tools.list_ports
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from html import unescape
from tkinter import Tk, Toplevel, messagebox
from tkinter import ttk
from PIL import Image
from pystray import Icon as TrayIcon, Menu as TrayMenu, MenuItem as TrayMenuItem

def _get_foreground_window_title():
    """Devuelve el título de la ventana activa (str, puede ser '')."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""
    except Exception:
        return ""

def _is_notepad_window(title: str) -> bool:
    t = (title or "").lower()
    # cubrimos "Bloc de notas" (ES), "Notepad" (EN) y variantes UWP
    return ("bloc de notas" in t) or ("notepad" in t)

def _is_browser_window(title: str) -> bool:
    # No es perfecto, pero suficiente para decidir el modo de selección
    t = (title or "").lower()
    return ("chrome" in t) or ("edge" in t) or ("firefox" in t) or ("brave" in t)

VERSION = "3.7"
LIC_FILE = "licencia.key"
CACHE_FILE = "licencia_activada.json"
LOG_FILE = "logs/licencias.log"
CONFIG_DIR = "configs"
CONFIG_ACTUAL = os.path.join(CONFIG_DIR, "config_actual.json")
CONFIG_DEFECTO = os.path.join(CONFIG_DIR, "formulario_visitantes.json")

ICON_CANDIDATES = [
    os.path.join(os.path.dirname(sys.argv[0]), "assets", "DMS_icono_circulo_i.ico"),
    os.path.join(os.path.dirname(sys.argv[0]), "assets", "icono.ico"),
    os.path.join(os.path.dirname(sys.argv[0]), "DMS_icono_circulo_i.ico"),
]
ICON_ASSETS_PATH = next((x for x in ICON_CANDIDATES if os.path.exists(x)), ICON_CANDIDATES[0])
LAST_COM_FILE = os.path.join(CONFIG_DIR, "ultimo_com.json")

READ_IDLE_SECONDS = 0.65
READ_MAX_BYTES = 900
TSE_ONLINE_TIMEOUT = 8

COLOR_BG = "#212121"
COLOR_TEXT = "white"
COLOR_ACCENT = "#e53935"

# =========================
# Instancia única (Windows)
# =========================
_SINGLETON_MUTEX = None
SELECT_MODE = "home_end"  # "none" | "home_end" | "ctrl_a"

# --- Anti-lecturas encimadas / control de concurrencia ---
COOLDOWN_SECONDS = 1.0  # protección anti doble lectura, sin bloquear cédulas consecutivas
_processing_lock = threading.Lock()
_last_read_ts = 0.0

# =========================
# Velocidades y pausas para escritura estable
# =========================
TYPE_INTERVAL = 0.03      # segundos entre caracteres (0.02–0.05 recomendable)
TAB_PAUSE = 0.04          # pausa breve entre tabs
BETWEEN_FIELDS = 0.10     # pausa entre campos
USE_CLIPBOARD = True      # True = pegar con portapapeles; False = teclear lento

# ——— Opciones para Ñ ———
KEEP_ENYE = True              # True = conservar Ñ/ñ, False = permitir reemplazo
REPLACE_ENYE_WITH_N = False   # True = forzar Ñ->N y ñ->n (usa junto con KEEP_ENYE=False)

# Pausa automática corta en cada acción de pyautogui
pyautogui.PAUSE = 0.02

# Campos críticos (se re-pegan para minimizar riesgo de truncado)
CRITICAL_FIELDS = {
    "Apellidos",
    "Primer Apellido",
    "Segundo Apellido",
    "Nombre",
    "Fecha de Nacimiento",
    "Fecha de Expiracion",
    "Fecha de Expiración"
}

# =========================
# Helpers de codificación/normalización (Ñ, tildes y caracteres especiales)
# =========================
def _normalize_text(s: str) -> str:
    """Limpia texto sin eliminar Ñ, tildes ni caracteres latinos válidos."""
    if s is None:
        return ""
    import unicodedata, re
    s = str(s).replace("\x00", " ").replace("\ufeff", " ")
    s = "".join(ch for ch in s if unicodedata.category(ch)[0] != "C" or ch in "\r\n\t")
    s = re.sub(r"[ \t]+", " ", s).strip()
    if REPLACE_ENYE_WITH_N and not KEEP_ENYE:
        s = s.replace("Ñ", "N").replace("ñ", "n")
    return s

def _normalize_enye(s: str) -> str:
    return _normalize_text(s)

def _decode_bytes_with_fallback(raw: bytes) -> str:
    """
    Decodifica sin botar Ñ/tildes. Prueba UTF-8, CP1252 y Latin-1.
    Latin-1/CP1252 se usan porque varios lectores seriales entregan bytes de 1 carácter.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return _normalize_text(raw)
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return _normalize_text(raw.decode(enc))
        except Exception:
            pass
    return _normalize_text(raw.decode("cp1252", errors="replace"))

def _text_noise_score(text: str) -> float:
    """Detecta basura tipo 'ã¢2Ý...' para evitar escribir licencias/documentos no soportados."""
    import unicodedata
    text = str(text or "")
    if not text:
        return 0.0
    suspicious = 0
    for ch in text:
        cat = unicodedata.category(ch)
        if ch == "�" or (cat[0] == "C" and ch not in "\r\n\t"):
            suspicious += 3
        elif cat[0] == "S":
            suspicious += 2
        elif ch in "¢£¤¥¦§¨©ª«¬®¯°±²³´µ¶·¸¹º»¼½¾¿×÷ÞþÐðÝýãÃ":
            suspicious += 2
    return suspicious / max(len(text), 1)

def _is_clean_name_text(value: str) -> bool:
    import re
    value = _normalize_text(value)
    if not value:
        return True
    return re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ .\-']{1,90}", value) is not None

def _valid_date_ddmmyyyy(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return True
    try:
        datetime.strptime(value, "%d/%m/%Y")
        return True
    except Exception:
        return False

def _base_person(tipo="DESCONOCIDO"):
    return {
        "TipoCedulaDetectado": tipo,
        "Cedula": "",
        "Apellidos": "",
        "Primer Apellido": "",
        "Segundo Apellido": "",
        "Nombre": "",
        "Sexo": "DESCONOCIDO",
        "Fecha de Nacimiento": "",
        "Fecha de Expiracion": "",
        "Fecha de Expiración": "",
        "Fecha de Emision": ""
    }

def _empty_person(tipo="NO_RECONOCIDA", raw_preview=""):
    data = _base_person(tipo)
    data["DebugRawPreview"] = raw_preview
    return data

def _is_probably_valid_person(datos: dict) -> bool:
    """Valida antes de escribir. Sexo DESCONOCIDO no invalida si lo demás está bien."""
    if not isinstance(datos, dict):
        return False
    tipo = str(datos.get("TipoCedulaDetectado", "")).upper()
    if tipo in {"NO_RECONOCIDA", "DESCONOCIDO"}:
        return False

    # Formato mdoc/ISO18013: no siempre trae datos visibles ni número de cédula
    # dentro del QR; puede traer únicamente un endpoint firmado. Lo aceptamos como
    # documento reconocido si logramos extraer una URL válida del TSE, y los campos
    # no disponibles se escriben como DESCONOCIDO según la configuración.
    if tipo == "TSE_MDOC_ISO18013":
        documento_url = _normalize_text(datos.get("DocumentoURL", ""))
        return documento_url.startswith("https://") and "servicioidc.tse.go.cr" in documento_url

    ced = str(datos.get("Cedula", "")).strip().replace("-", "")
    nombre = _normalize_text(datos.get("Nombre", ""))
    p_ap = _normalize_text(datos.get("Primer Apellido", ""))
    s_ap = _normalize_text(datos.get("Segundo Apellido", ""))
    apellidos = _normalize_text(datos.get("Apellidos", "")) or f"{p_ap} {s_ap}".strip()
    if not ced.isdigit() or not (5 <= len(ced) <= 12):
        return False

    # Los QR URL del TSE pueden venir con datos completos si hay internet,
    # o solo con la cédula si la consulta online falla/expira.
    # En ese caso permitimos escribir la cédula y dejamos lo demás como DESCONOCIDO,
    # sin marcarlo como documento basura.
    if tipo == "TSE_QR_URL":
        nombre = nombre or "DESCONOCIDO"
        apellidos = apellidos or "DESCONOCIDO"

    if not nombre or not apellidos:
        return False
    joined = " ".join(str(v) for v in datos.values() if isinstance(v, (str, int, float)))
    if _text_noise_score(joined) > 0.10:
        return False
    for field in (nombre, p_ap, s_ap, apellidos):
        if field and not _is_clean_name_text(field):
            return False
    for key in ("Fecha de Nacimiento", "Fecha de Expiracion", "Fecha de Expiración", "Fecha de Emision"):
        if not _valid_date_ddmmyyyy(str(datos.get(key, ""))):
            return False
    return True

def guardar_raw_no_reconocido(raw: bytes, motivo: str = "formato_no_reconocido"):
    try:
        import base64
        os.makedirs("logs/lecturas_no_reconocidas", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join("logs/lecturas_no_reconocidas", f"{ts}.json")
        payload = {
            "fecha": datetime.now().isoformat(),
            "motivo": motivo,
            "len": len(raw or b""),
            "preview_text": _decode_bytes_with_fallback(raw or b"")[:500],
            "hex": (raw or b"").hex(),
            "base64": base64.b64encode(raw or b"").decode("ascii")
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ No se pudo guardar lectura desconocida: {e}")

def ensure_single_instance():
    """
    Evita múltiples instancias usando un mutex con nombre del sistema.
    Si ya existe, muestra un aviso y termina el proceso actual.
    """
    global _SINGLETON_MUTEX
    try:
        mutex_name = "Global\\DMS_QRReader_SingleInstance_v33"
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        # 183 = ERROR_ALREADY_EXISTS
        already_exists = ctypes.windll.kernel32.GetLastError() == 183
        if already_exists:
            try:
                ctypes.windll.user32.MessageBoxW(
                    0,
                    "La aplicación ya se está ejecutando.",
                    "Instancia en ejecución",
                    0x40  # MB_ICONINFORMATION
                )
            except Exception:
                pass
            sys.exit(0)
        _SINGLETON_MUTEX = handle  # mantener la referencia viva
    except Exception:
        # Si algo falla (p.ej., no Windows), no bloqueamos la ejecución
        pass


def cargar_icono():
    try:
        return Image.open(ICON_ASSETS_PATH)
    except Exception as e:
        print(f"⚠️ No se pudo cargar el ícono desde assets: {e}")
        return None


class SelectorConfiguracionGUI:
    def __init__(self, root=None):
        self.ventana = Toplevel(root) if root else Tk()
        self.ventana.title("Seleccionar Configuración")
        self.ventana.geometry("420x250")
        self.ventana.resizable(False, False)
        self.ventana.configure(bg=COLOR_BG)

        try:
            self.ventana.iconbitmap(default=ICON_ASSETS_PATH)
        except Exception as e:
            print(f"⚠️ No se pudo aplicar ícono a la ventana: {e}")

        self.ventana.update_idletasks()
        w = self.ventana.winfo_width()
        h = self.ventana.winfo_height()
        x = (self.ventana.winfo_screenwidth() // 2) - (w // 2)
        y = (self.ventana.winfo_screenheight() // 2) - (h // 2)
        self.ventana.geometry(f"+{x}+{y}")

        style = ttk.Style(self.ventana)
        style.theme_use("clam")
        style.configure("TFrame", background=COLOR_BG)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=("Segoe UI", 12))
        style.configure("TButton", font=("Segoe UI", 11), padding=6, background=COLOR_ACCENT, foreground="white")
        style.configure("TCombobox", font=("Segoe UI", 11))

        frame = ttk.Frame(self.ventana, padding=20, style="TFrame")
        frame.pack(expand=True)

        ttk.Label(frame, text="Seleccione la configuración que desea activar:", style="TLabel").pack(pady=(10, 10))

        disponibles = [f for f in os.listdir(CONFIG_DIR) if f.endswith('.json') and f != 'config_actual.json']
        if not disponibles:
            messagebox.showerror("Sin configuraciones", "No hay configuraciones disponibles.")
            self.ventana.destroy()
            return

        self.combo = ttk.Combobox(frame, values=disponibles, state='readonly', width=40)
        self.combo.pack(pady=(0, 20))
        self.combo.set(disponibles[0])

        ttk.Button(frame, text="Activar", command=self.guardar_seleccion, style="TButton").pack()

        self.ventana.grab_set()
        self.ventana.focus_force()
        self.ventana.wait_window()

    def guardar_seleccion(self):
        seleccion = self.combo.get()
        if seleccion:
            try:
                with open(CONFIG_ACTUAL, 'w', encoding='utf-8') as f:
                    json.dump({"activa": seleccion}, f, indent=2)
                self.ventana.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo guardar la configuración: {e}")



def cargar_ultimo_com():
    try:
        with open(LAST_COM_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        puerto = (data.get("puerto") or "").strip()
        return puerto or None
    except Exception:
        return None

def guardar_ultimo_com(puerto):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(LAST_COM_FILE, "w", encoding="utf-8") as f:
            json.dump({"puerto": puerto, "fecha": datetime.now().isoformat()}, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ No se pudo guardar el último COM: {e}")

def puerto_responde(puerto, callback_log=None, segundos=3):
    if not puerto:
        return False
    try:
        if callback_log:
            callback_log(f"🔁 Probando último puerto guardado: {puerto}... pase la cédula")
        with serial.Serial(puerto, baudrate=9600, timeout=0.2) as ser:
            ser.reset_input_buffer()
            buffer = bytearray()
            start = time.time()
            while time.time() - start < segundos:
                if ser.in_waiting:
                    buffer.extend(ser.read(ser.in_waiting))
                    if len(buffer) >= 100 or buffer.endswith(b"\r\n"):
                        if callback_log:
                            callback_log(f"✅ {puerto} respondió correctamente")
                        return True
                time.sleep(0.01)
        if callback_log:
            callback_log(f"⚠️ {puerto} no respondió. Buscando otro COM...")
        return False
    except Exception as e:
        if callback_log:
            callback_log(f"⚠️ {puerto} no disponible: {e}. Buscando otro COM...")
        return False

def inicializar_configuracion():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_DEFECTO):
        config = {
            "nombre": "Formulario Visitantes",
            "campos": [
                {"dato": "Primer Apellido", "tabuladores": 0},
                {"dato": "Nombre", "tabuladores": 0},
                {"dato": "Cedula", "tabuladores": 1},
                {"dato": "Fecha de Nacimiento", "tabuladores": 2}
            ]
        }
        with open(CONFIG_DEFECTO, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    if not os.path.exists(CONFIG_ACTUAL):
        with open(CONFIG_ACTUAL, "w", encoding="utf-8") as f:
            json.dump({"activa": "formulario_visitantes.json"}, f, indent=2)


def cargar_configuracion_activa():
    try:
        with open(CONFIG_ACTUAL, "r", encoding="utf-8") as f:
            activa = json.load(f)["activa"]
        with open(os.path.join(CONFIG_DIR, activa), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error al cargar la configuración activa: {e}")
        return None


def validar_licencia():
    os.makedirs("logs", exist_ok=True)
    lic_data = None

    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            lic_data = json.load(f)
    elif os.path.exists(LIC_FILE):
        with open(LIC_FILE, "r", encoding="utf-8") as f:
            lic_data = json.load(f)
        with open(CACHE_FILE, "w", encoding="utf-8") as cache:
            json.dump(lic_data, cache)

    if lic_data:
        try:
            expira = datetime.fromisoformat(lic_data["expira"])
            if datetime.now() > expira:
                os.remove(CACHE_FILE)
                if os.path.exists(LIC_FILE):
                    os.remove(LIC_FILE)
                ctypes.windll.user32.MessageBoxW(0, "La licencia ha expirado.", "Licencia Inválida", 0x10)
                sys.exit(1)
            return True
        except Exception as e:
            print(f"Error al verificar licencia: {e}")
            return False
    else:
        ctypes.windll.user32.MessageBoxW(0, "No se encontró una licencia válida.", "Licencia Requerida", 0x10)
        sys.exit(1)


def decode_cedula_data(encoded_bytes):
    """ADULTO (binario XOR + offsets). Devuelve el mismo esquema de campos que usa la config."""
    xor_key = bytearray([39, 48, 4, 160, 0, 15, 147, 18, 160, 209, 51, 224, 3, 208, 0, 223, 0])
    decoded_bytes = bytearray(len(encoded_bytes))
    for i in range(len(encoded_bytes)):
        decoded_bytes[i] = encoded_bytes[i] ^ xor_key[i % len(xor_key)]

    def extract(data, start, length):
        raw = bytes(data[start:start+length])
        s = _decode_bytes_with_fallback(raw)    # evita perder Ñ/acentos
        s = s.split('\x00')[0].strip()
        s = _normalize_enye(s)                  # aplica mapeo Ñ->N si así lo configuras
        return s

    sexo_raw = extract(decoded_bytes, 91, 1).upper()
    sexo = "MASCULINO" if sexo_raw == "M" else "FEMENINO" if sexo_raw == "F" else "DESCONOCIDO"

    def formato_fecha(fecha):
        return f"{fecha[6:8]}/{fecha[4:6]}/{fecha[0:4]}" if len(fecha) == 8 else fecha

    cedula  = extract(decoded_bytes, 0, 9)
    p_ap    = extract(decoded_bytes, 9, 26)
    s_ap    = extract(decoded_bytes, 35, 26)
    nombre  = extract(decoded_bytes, 61, 30)
    ap_full = f"{p_ap} {s_ap}".strip()

    return {
        "TipoCedulaDetectado": "ADULTO_XOR",
        "Cedula": cedula,
        "Apellidos": ap_full,
        "Primer Apellido": p_ap,
        "Segundo Apellido": s_ap,
        "Nombre": nombre,
        "Sexo": sexo,
        "Fecha de Nacimiento": formato_fecha(extract(decoded_bytes, 92, 8)),
        "Fecha de Expiracion": formato_fecha(extract(decoded_bytes, 100, 8)),
        # Alias con acento por compatibilidad con tus configuraciones críticas
        "Fecha de Expiración": formato_fecha(extract(decoded_bytes, 100, 8)),
        # Campo opcional (en adulto no viene): lo dejamos vacío para unificar etiquetas
        "Fecha de Emision": ""
    }

def _ddmmyyyy_to_dd_mm_yyyy(s):
    """Convierte DDMMYYYY -> DD/MM/YYYY (si aplica)"""
    if s and len(s) == 8 and s.isdigit():
        return f"{s[0:2]}/{s[2:4]}/{s[4:8]}"
    return s



def _extract_tse_table_value(html_text: str, label: str) -> str:
    """Extrae valores de la tabla HTML del TSE por etiqueta visible."""
    import re
    pattern = (
        r"<tr[^>]*>\s*<th[^>]*>\s*" + re.escape(label) +
        r"\s*</th>\s*<td[^>]*>(.*?)</td>\s*</tr>"
    )
    m = re.search(pattern, html_text or "", flags=re.I | re.S)
    if not m:
        return ""
    value = re.sub(r"<[^>]+>", "", m.group(1))
    return _normalize_text(unescape(value))


def _parse_tse_html(html_text: str, cedula: str) -> dict:
    """Convierte el HTML del TSE en el mismo diccionario estándar del lector."""
    datos = _base_person("TSE_QR_URL")
    datos.update({
        "Cedula": _normalize_text(cedula),
        "Nombre": "DESCONOCIDO",
        "Primer Apellido": "DESCONOCIDO",
        "Segundo Apellido": "",
        "Apellidos": "DESCONOCIDO",
        "Sexo": "DESCONOCIDO",
        "Fecha de Nacimiento": "",
        "Fecha de Expiracion": "",
        "Fecha de Expiración": "",
        "Fecha de Emision": "",
        "Lugar de Nacimiento": "",
        "Lugar de Residencia": "",
        "Padre": "",
        "Madre": "",
    })

    nombre = _extract_tse_table_value(html_text, "Nombre")
    p_ap = _extract_tse_table_value(html_text, "Primer Apellido")
    s_ap = _extract_tse_table_value(html_text, "Segundo Apellido")
    fecha_nac = _extract_tse_table_value(html_text, "Fecha de Nacimiento")
    fecha_venc = _extract_tse_table_value(html_text, "Fecha de Vencimiento")

    if nombre:
        datos["Nombre"] = nombre
    if p_ap:
        datos["Primer Apellido"] = p_ap
    if s_ap:
        datos["Segundo Apellido"] = s_ap

    apellidos = f"{datos.get('Primer Apellido','')} {datos.get('Segundo Apellido','')}".strip()
    if apellidos and "DESCONOCIDO" not in apellidos:
        datos["Apellidos"] = apellidos

    if fecha_nac:
        datos["Fecha de Nacimiento"] = fecha_nac
    if fecha_venc:
        datos["Fecha de Expiracion"] = fecha_venc
        datos["Fecha de Expiración"] = fecha_venc

    return datos


def _consultar_tse_online(url: str, cedula: str) -> dict:
    """
    Consulta el QR URL del TSE y extrae los datos visibles en HTML.
    Si no hay internet, si el token expira o si requests no está instalado,
    devuelve datos parciales seguros: cédula + DESCONOCIDO.
    """
    datos = _parse_tse_html("", cedula)
    datos["TSE_Consulta"] = "SIN_CONSULTAR"

    try:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-CR,es;q=0.9,en;q=0.8",
        }
        response = requests.get(url, headers=headers, timeout=TSE_ONLINE_TIMEOUT)
        html_text = response.text or ""
        datos["TSE_StatusCode"] = str(response.status_code)
        if response.status_code >= 400 or not html_text:
            datos["TSE_Consulta"] = "ERROR_HTTP"
            return datos

        datos = _parse_tse_html(html_text, cedula)
        datos["TSE_StatusCode"] = str(response.status_code)
        datos["TSE_Consulta"] = "OK" if datos.get("Nombre") != "DESCONOCIDO" else "SIN_DATOS_VISIBLES"
        return datos

    except Exception as e:
        datos["TSE_Consulta"] = "ERROR"
        datos["TSE_Error"] = str(e)[:180]
        guardar_log(f"⚠️ Consulta TSE falló: {e}")
        return datos


def _try_parse_mdoc_iso18013(raw: bytes):
    """
    Detecta documentos móviles tipo mdoc/ISO18013.

    Este QR no trae necesariamente nombre/cédula en texto plano; normalmente trae
    un payload Base64URL con un endpoint del TSE. El objetivo aquí es reconocerlo
    como formato válido, extraer la URL del TSE y evitar que el sistema lo trate
    como basura o documento no soportado.
    """
    import base64
    import re

    txt = _decode_bytes_with_fallback(raw).strip()
    if not txt.lower().startswith("mdoc:"):
        return None

    payload = txt.split(":", 1)[1].strip().split()[0]
    decoded = b""

    try:
        padding = "=" * ((4 - len(payload) % 4) % 4)
        decoded = base64.urlsafe_b64decode((payload + padding).encode("ascii"))
    except Exception as e:
        guardar_log(f"⚠️ No se pudo decodificar mdoc Base64URL: {e}")

    documento_url = ""
    version_mdoc = ""

    if decoded:
        try:
            urls = re.findall(rb"https?://[^\x00-\x20]+", decoded)
            if urls:
                # Preferimos el endpoint oficial de servicio IDC del TSE.
                candidatos = [u for u in urls if b"servicioidc.tse.go.cr" in u] or urls
                documento_url = candidatos[0].decode("utf-8", errors="ignore")
                documento_url = _normalize_text(documento_url)

            m_ver = re.search(rb"c\d+\.\d+", decoded)
            if m_ver:
                version_mdoc = m_ver.group(0).decode("ascii", errors="ignore")
        except Exception as e:
            guardar_log(f"⚠️ Error extrayendo datos mdoc: {e}")

    datos = _base_person("TSE_MDOC_ISO18013")
    datos.update({
        "Cedula": "DESCONOCIDO",
        "Nombre": "DESCONOCIDO",
        "Primer Apellido": "DESCONOCIDO",
        "Segundo Apellido": "",
        "Apellidos": "DESCONOCIDO",
        "Sexo": "DESCONOCIDO",
        "Fecha de Nacimiento": "",
        "Fecha de Expiracion": "",
        "Fecha de Expiración": "",
        "Fecha de Emision": "",
        "Lugar de Nacimiento": "",
        "Lugar de Residencia": "",
        "Padre": "",
        "Madre": "",
        "DocumentoURL": documento_url,
        "MDocVersion": version_mdoc,
        "MDocTipo": "ISO18013",
        "MDocPayloadPreview": payload[:120],
    })

    if not documento_url:
        return None

    return datos


def _try_parse_tse_url(raw: bytes):
    """Detecta QR URL del TSE, extrae cédula y consulta datos online cuando se puede."""
    import re
    txt = _decode_bytes_with_fallback(raw).strip()
    m = re.search(r"https://www\.consulta\.tse\.go\.cr/consultacedula/Cedula\?[^\s\r\n]+", txt, flags=re.I)
    if not m:
        return None

    url = m.group(0).strip()
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        cedula = _normalize_text((qs.get("cedula") or [""])[0])
        sol = _normalize_text((qs.get("sol") or [""])[0])
        sign = _normalize_text((qs.get("sign") or [""])[0])
    except Exception:
        return None

    if not (cedula.isdigit() and 5 <= len(cedula) <= 12):
        return None

    datos = _consultar_tse_online(url, cedula)
    datos["TipoCedulaDetectado"] = "TSE_QR_URL"
    datos["Cedula"] = cedula
    # Importante: NO usar sol como Fecha de Emision porque no es fecha dd/mm/yyyy.
    # Si se guarda ahí, la validación rechaza el documento como no confiable.
    datos["TSE_Sol"] = sol
    datos["TSE_Sign"] = sign
    datos["TSE_URL"] = url
    return datos

def _try_parse_minor_csv(raw: bytes):
    """
    CSV legible (menor o cédula nueva/adulta) seguido opcionalmente de bloque binario.
    Formato observado:
    "CEDULA",DDMMYYYY_emision,DDMMYYYY_nacimiento,"PADRE","MADRE",AP1,AP2,"NOMBRE",,SEXO,
    "LUG_NAC","LUG_RES",TIPO,I% + cola binaria opcional

    Importante:
    - NO rechaza si después del CSV viene binario.
    - NO falla si el sexo viene vacío/no estándar; usa DESCONOCIDO.
    - Conserva Ñ, tildes y caracteres especiales.
    """
    import csv, io, re

    txt = _decode_bytes_with_fallback(raw)

    # Inicio real del CSV: "8 a 12 dígitos",fecha_emision,fecha_nacimiento,
    m = re.search(r'"(\d{8,12})",\d{8},\d{8},', txt)
    if not m:
        # Compatibilidad con variantes donde solo se detecta la cédula entre comillas.
        m = re.search(r'"(\d{8,12})",', txt)
    if not m:
        return None

    tail = txt[m.start():]

    # Cédulas nuevas pueden traer CSV + bloque binario/padding.
    # En las muestras, la parte útil termina en ,D,I% o variante similar.
    end_match = re.search(r',([A-Z]),(I%)', tail)
    if end_match:
        line = tail[:end_match.end()]
    else:
        line = tail.splitlines()[0].strip()

    line = line.replace("\x00", "").strip()

    try:
        reader = csv.reader(io.StringIO(line), delimiter=",", quotechar='"')
        fields = next(reader)
    except Exception:
        return None

    if len(fields) < 13:
        return None

    while len(fields) < 14:
        fields.append("")

    f_ced = _normalize_text((fields[0] or "").strip().strip('"'))
    f_emision = _normalize_text((fields[1] or "").strip())
    f_nac = _normalize_text((fields[2] or "").strip())

    if not (f_ced.isdigit() and 5 <= len(f_ced) <= 12):
        return None

    fecha_emision = _ddmmyyyy_to_dd_mm_yyyy(f_emision) if (len(f_emision) == 8 and f_emision.isdigit()) else ""
    fecha_nacimiento = _ddmmyyyy_to_dd_mm_yyyy(f_nac) if (len(f_nac) == 8 and f_nac.isdigit()) else ""

    padre   = _normalize_text(fields[3])
    madre   = _normalize_text(fields[4])
    p_ap    = _normalize_text(fields[5])
    s_ap    = _normalize_text(fields[6])
    nombre  = _normalize_text(fields[7])
    sexo_raw = _normalize_text(fields[9]).upper()
    sexo = {
        "M": "MASCULINO",
        "F": "FEMENINO",
        "1": "MASCULINO",
        "2": "FEMENINO"
    }.get(sexo_raw, "DESCONOCIDO")

    lug_nac = _normalize_text(fields[10])
    lug_res = _normalize_text(fields[11])

    ced = f_ced.lstrip("0") or f_ced
    tipo = "CSV_EXTENDIDA" if len(raw or b"") > 250 else "MENOR_CSV"

    return {
        "TipoCedulaDetectado": tipo,
        "Cedula": ced,
        "Apellidos": f"{p_ap} {s_ap}".strip(),
        "Primer Apellido": p_ap,
        "Segundo Apellido": s_ap,
        "Nombre": nombre,
        "Sexo": sexo,
        "Fecha de Nacimiento": fecha_nacimiento,
        "Fecha de Expiracion": "",
        "Fecha de Expiración": "",
        "Fecha de Emision": fecha_emision,
        "Lugar de Nacimiento": lug_nac,
        "Lugar de Residencia": lug_res,
        "Padre": padre,
        "Madre": madre,
        "EsMenor": tipo == "MENOR_CSV"
    }

def parse_cedula_unificada(raw: bytes):
    """
    Detecta QR URL TSE, mdoc/ISO18013, MENOR/CSV o ADULTO XOR.
    Si no reconoce datos confiables, NO devuelve una persona válida.
    """
    try:
        tse = _try_parse_tse_url(raw)
        if tse and _is_probably_valid_person(tse):
            return tse
    except Exception as e:
        guardar_log(f"⚠️ Parser TSE_QR_URL falló: {e}")

    try:
        mdoc = _try_parse_mdoc_iso18013(raw)
        if mdoc and _is_probably_valid_person(mdoc):
            return mdoc
    except Exception as e:
        guardar_log(f"⚠️ Parser TSE_MDOC_ISO18013 falló: {e}")

    try:
        menor = _try_parse_minor_csv(raw)
        if menor and _is_probably_valid_person(menor):
            return menor
    except Exception as e:
        guardar_log(f"⚠️ Parser MENOR_CSV falló: {e}")

    try:
        adulto = decode_cedula_data(raw)
        # Acepta sexo DESCONOCIDO si cédula, nombre, apellido y fechas están bien.
        if adulto and _is_probably_valid_person(adulto):
            return adulto
    except Exception as e:
        guardar_log(f"⚠️ Parser ADULTO_XOR falló: {e}")

    preview = _decode_bytes_with_fallback(raw)[:160].replace("\n", "\\n")
    guardar_raw_no_reconocido(raw, "ningun_parser_valido")
    return _empty_person("NO_RECONOCIDA", preview)

# =========================
# Escritura robusta
# =========================
def safe_tab(n=1):
    """Envía n tabs con pequeñas pausas para evitar perderse."""
    for _ in range(max(0, int(n))):
        pyautogui.press("tab")
        time.sleep(TAB_PAUSE)

def _set_clipboard_text_windows(texto: str) -> bool:
    """Portapapeles Unicode nativo para conservar Ñ, tildes y caracteres especiales."""
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        data = (str(texto) + "\0").encode("utf-16le")
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            h_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h_global:
                return False
            locked = kernel32.GlobalLock(h_global)
            if not locked:
                return False
            ctypes.memmove(locked, data, len(data))
            kernel32.GlobalUnlock(h_global)
            user32.SetClipboardData(CF_UNICODETEXT, h_global)
        finally:
            user32.CloseClipboard()
        return True
    except Exception as e:
        print(f"⚠️ Clipboard Windows falló: {e}")
        return False

def write_via_clipboard(texto):
    """Pega texto Unicode. Si Windows falla, usa Tk como respaldo."""
    if _set_clipboard_text_windows(texto):
        pyautogui.hotkey("ctrl", "v")
        return
    try:
        aux = Tk()
        aux.withdraw()
        aux.clipboard_clear()
        aux.clipboard_append(str(texto))
        aux.update()
        aux.destroy()
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        pyautogui.write(str(texto), interval=TYPE_INTERVAL)

def safe_write(texto):
    """Escribe texto de forma robusta: portapapeles (ideal) o tecleo lento."""
    if not texto:
        return
    # Si hay caracteres no ASCII (Ñ, acentos…), obligamos portapapeles para no perderlos.
    if any(ord(c) > 127 for c in texto):
        write_via_clipboard(texto)
        return
    if USE_CLIPBOARD:
        write_via_clipboard(texto)
    else:
        pyautogui.write(texto, interval=TYPE_INTERVAL)

def select_current_line_via_home_end():
    """Selecciona SOLO la línea actual (sin usar Ctrl+A)."""
    pyautogui.press("home")
    time.sleep(0.02)
    pyautogui.keyDown("shift")
    pyautogui.press("end")
    pyautogui.keyUp("shift")
    time.sleep(0.02)

def write_field_value(valor, is_critical=False):
    """
    Escribe un valor en el campo actual.
    - Si es crítico, primero selecciona el contenido del campo (según la app activa) y luego pega una sola vez.
    - Si no es crítico, simplemente escribe/pega una sola vez.
    """
    if not valor:
        return

    # Pausa mínima para asegurar foco
    time.sleep(0.03)

    if is_critical:
        title = _get_foreground_window_title()
        # En Bloc de notas / Notepad: usar Home+Shift+End (evita efectos secundarios)
        if _is_notepad_window(title) and not _is_browser_window(title):
            select_current_line_via_home_end()
        else:
            # En navegadores y la mayoría de apps, Ctrl+A es fiable
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.02)

        # Pegar/Escribir una única vez
        safe_write(valor)
    else:
        # Campos no críticos: una sola escritura/pegado
        safe_write(valor)


def escribir_con_configuracion(datos, config):
    """
    Navega con tabs y escribe cada campo de forma robusta.
    - Pausas breves entre tabs y campos
    - Escritura por portapapeles o tecleo lento (configurable)
    """
    campos = config.get("campos", [])
    for campo in campos:
        # Moverse con tabs (si la config lo pide)
        safe_tab(campo.get("tabuladores", 0))

        # Obtener valor y escribirlo con método robusto
        etiqueta = (campo.get("dato") or "").strip()
        valor = datos.get(etiqueta, "")
        is_critical = etiqueta in CRITICAL_FIELDS
        write_field_value(valor, is_critical=is_critical)

        # Avanzar al siguiente campo (1 tab final como en tu flujo actual)
        pyautogui.press("tab")
        time.sleep(BETWEEN_FIELDS)


def guardar_log(datos):
    os.makedirs("logs", exist_ok=True)
    with open("logs/detalle.log", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now()}] {datos}\n")


def _esperar_serial_silencioso(ser, quiet_seconds=0.35, timeout=2.0):
    start = time.time()
    quiet_start = time.time()
    while time.time() - start < timeout:
        if ser.in_waiting:
            ser.read(ser.in_waiting)
            quiet_start = time.time()
        elif time.time() - quiet_start >= quiet_seconds:
            return
        time.sleep(0.01)

def _leer_buffer_serial(ser, timeout_total=9, max_bytes=READ_MAX_BYTES, idle_seconds=READ_IDLE_SECONDS):
    """Lee una lectura completa y espera silencio real antes de procesar."""
    buffer = bytearray()
    start_time = time.time()
    last_data = None
    while time.time() - start_time < timeout_total:
        waiting = ser.in_waiting
        if waiting:
            chunk = ser.read(waiting)
            if chunk:
                buffer.extend(chunk)
                last_data = time.time()
                if len(buffer) > max_bytes:
                    return bytes(buffer)
        else:
            if buffer and last_data and (time.time() - last_data) >= idle_seconds:
                time.sleep(0.08)
                if ser.in_waiting:
                    continue
                break
        time.sleep(0.005)
    return bytes(buffer)

def _buffer_parece_mezclado_o_incompleto(raw: bytes):
    """
    Validación mínima del buffer serial.
    Las cédulas nuevas pueden traer bloque binario después del CSV con varios bytes
    0x0D/0x0A. Por eso NO se rechaza por cantidad de saltos de línea.
    El parser decide si los datos son válidos o si se deben mandar a desconocidos.
    """
    if not raw or len(raw) < 8:
        return True, "buffer_demasiado_corto"
    if len(raw) > READ_MAX_BYTES:
        return True, "buffer_demasiado_largo_posible_mezcla"
    return False, ""

def escuchar_en_segundo_plano(puerto):
    """
    Escucha robusta:
    - Evita buffers mezclados si se cambia de documento rápido.
    - No escribe lecturas incompletas.
    - No escribe licencias u otros documentos no reconocidos.
    """
    global _last_read_ts
    try:
        with serial.Serial(puerto, baudrate=9600, timeout=0.2) as ser:
            ser.reset_input_buffer()
            _esperar_serial_silencioso(ser)
            while True:
                buffer = _leer_buffer_serial(ser)
                es_malo, motivo = _buffer_parece_mezclado_o_incompleto(buffer)
                if es_malo:
                    if buffer:
                        guardar_raw_no_reconocido(buffer, motivo)
                        guardar_log(f"⚠️ Lectura ignorada: {motivo}. No se escribió en pantalla.")
                    ser.reset_input_buffer()
                    _esperar_serial_silencioso(ser, quiet_seconds=0.35)
                    continue

                now = time.time()
                with _processing_lock:
                    if (now - _last_read_ts) < COOLDOWN_SECONDS:
                        guardar_log("⚠️ Lectura ignorada por protección anti-doble lectura rápida.")
                        ser.reset_input_buffer()
                        _esperar_serial_silencioso(ser, quiet_seconds=0.35)
                        continue
                    _last_read_ts = now

                try:
                    datos = parse_cedula_unificada(buffer)
                    guardar_log(datos)
                    if not _is_probably_valid_person(datos):
                        guardar_raw_no_reconocido(buffer, "datos_no_confiables_o_documento_no_soportado")
                        guardar_log("⚠️ Lectura ignorada: documento no soportado o datos incompletos. No se escribió en pantalla.")
                        ser.reset_input_buffer()
                        _esperar_serial_silencioso(ser, quiet_seconds=0.35)
                        continue

                    config = cargar_configuracion_activa()
                    if config:
                        ser.reset_input_buffer()
                        time.sleep(0.15)
                        escribir_con_configuracion(datos, config)
                        time.sleep(0.25)
                        ser.reset_input_buffer()
                        _esperar_serial_silencioso(ser, quiet_seconds=0.35)
                except Exception as e:
                    guardar_log(f"⚠️ Error procesando lectura: {e}")
                    guardar_raw_no_reconocido(buffer, f"exception_{type(e).__name__}")
                finally:
                    time.sleep(0.05)
    except Exception as e:
        print(f"Error: {e}")

def ocultar_consola():
    ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)


def encontrar_lector_qr_por_actividad(callback_log):
    BAUDS = [9600]  # puedes agregar 115200 si lo configuras así
    for p in serial.tools.list_ports.comports():
        puerto = p.device
        for baud in BAUDS:
            callback_log(f"🧪 {puerto} Pasa la cédula")
            try:
                with serial.Serial(puerto, baudrate=baud, timeout=0.2) as ser:
                    ser.reset_input_buffer()
                    buffer = bytearray()
                    start_time = time.time()
                    while time.time() - start_time < 8:  # antes 5 s
                        if ser.in_waiting:
                            buffer.extend(ser.read(ser.in_waiting))
                        time.sleep(0.01)
                    if len(buffer) >= 200:  # antes 600
                        callback_log(f"✅ {puerto} detectado (len={len(buffer)})")
                        return puerto
            except Exception as e:
                callback_log(f"❌ {puerto} falló: {e}")
    callback_log("🔴 No se detectó lector QR.")
    return None


if __name__ == "__main__":
    # Instancia única ANTES de cualquier otra cosa
    ensure_single_instance()

    validar_licencia()
    inicializar_configuracion()

    com_final = None
    while com_final is None:
        estado_root = Tk()
        estado_root.title(f"Calibrando lector QR - v{VERSION}")
        estado_root.configure(bg=COLOR_BG)
        try:
            estado_root.iconbitmap(default=ICON_ASSETS_PATH)
        except Exception as e:
            print(f"⚠️ No se pudo aplicar ícono a ventana de calibración: {e}")

        style = ttk.Style(estado_root)
        style.theme_use("clam")
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=("Segoe UI", 12))

        label_estado = ttk.Label(estado_root, text="Inicializando...", font=("Segoe UI", 12))
        label_estado.pack(padx=30, pady=30)

        def actualizar_estado(msg):
            label_estado.config(text=msg)
            estado_root.update()

        com_detectado = []

        def calibrar():
            ultimo = cargar_ultimo_com()
            if ultimo and puerto_responde(ultimo, actualizar_estado, segundos=3):
                com_detectado.append(ultimo)
            else:
                com = encontrar_lector_qr_por_actividad(actualizar_estado)
                if com:
                    guardar_ultimo_com(com)
                    com_detectado.append(com)
            estado_root.destroy()

        threading.Thread(target=calibrar, daemon=True).start()
        estado_root.mainloop()

        if com_detectado:
            com_final = com_detectado[0]
        else:
            # Crear raíz temporal solo para el cuadro de diálogo
            aux = Tk()
            aux.withdraw()  # ocultar completamente la ventana raíz
            aux.attributes("-topmost", True)  # asegurar que el messagebox quede visible
            reintentar = messagebox.askretrycancel(
                "No se detectó lector",
                "No se detectó el lector QR.\n\n¿Desea intentar la calibración nuevamente?",
                parent=aux
            )
            aux.destroy()

            if not reintentar:
                sys.exit(0)  # cerrar por completo el programa

    # === Desde aquí en adelante todo queda igual que antes ===
    if com_final:
        root_global = Tk()
        try:
            root_global.iconbitmap(default=ICON_ASSETS_PATH)
        except Exception as e:
            print(f"⚠️ No se pudo aplicar ícono a ventana principal: {e}")
        root_global.withdraw()
        SelectorConfiguracionGUI(root_global)
        root_global.destroy()

        ocultar_consola()
        threading.Thread(target=escuchar_en_segundo_plano, args=(com_final,), daemon=True).start()

        def salir(icon, item=None):
            try:
                icon.stop()
            except Exception:
                pass
            os._exit(0)

        def cambiar_configuracion(icon, item=None):

            def abrir():

                try:
                    ventana = Tk()

                    ventana.withdraw()

                    selector = SelectorConfiguracionGUI(ventana)

                    try:
                        selector.ventana.attributes("-topmost", True)
                        selector.ventana.lift()
                        selector.ventana.focus_force()
                    except:
                        pass

                    ventana.mainloop()

                except Exception as e:
                    guardar_log(f"⚠️ Error abriendo selector desde bandeja: {e}")

            threading.Thread(
                target=abrir,
                daemon=True
            ).start()

        icon_image = cargar_icono()
        icon = TrayIcon("DMS_QR", icon_image, "DMS - Lector QR", menu=TrayMenu(
            TrayMenuItem("Cambiar configuración", cambiar_configuracion),
            TrayMenuItem("Salir", salir)
        ))
        icon.run()
