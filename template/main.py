import ctypes, json, os, shutil, sys, threading
from datetime import datetime
from tkinter import Tk, Toplevel, messagebox, ttk
from assets.runtime import lector_core as core

VERSION = "3.8.1"
HOTKEY = "Ctrl+Alt+C"
ROOT = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
CFG = os.path.join(ROOT, "configs")
FORMS = os.path.join(CFG, "formularios")
SYSTEM = os.path.join(CFG, "sistema")
FORMATS = os.path.join(CFG, "formatos")
ACTIVE = os.path.join(SYSTEM, "config_actual.json")
FAVORITES = os.path.join(SYSTEM, "favoritos.json")
LAST_COM = os.path.join(SYSTEM, "ultimo_com.json")
DEFAULT_FORM = os.path.join(FORMS, "formulario_visitantes.json")
_lock = threading.RLock()
_hotkey_tid = None


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def move_old(src, folder, name=None):
    if not os.path.isfile(src): return
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, name or os.path.basename(src))
    if os.path.exists(dst):
        try:
            if open(src, "rb").read() == open(dst, "rb").read(): os.remove(src); return
        except Exception: pass
        stem, ext = os.path.splitext(os.path.basename(dst))
        dst = os.path.join(folder, f"{stem}_migrada_{datetime.now():%Y%m%d_%H%M%S}{ext}")
    shutil.move(src, dst)


def migrate():
    for folder in (FORMS, SYSTEM, FORMATS): os.makedirs(folder, exist_ok=True)
    reserved = {
        "config_actual.json": (SYSTEM, None), "ultimo_com.json": (SYSTEM, None),
        "favoritos.json": (SYSTEM, None), "formatos_cedulas.json": (FORMATS, None),
    }
    for name, target in reserved.items(): move_old(os.path.join(CFG, name), *target)
    for name in os.listdir(CFG):
        path = os.path.join(CFG, name)
        if os.path.isfile(path) and name.lower().endswith(".json"): move_old(path, FORMS)


def forms():
    os.makedirs(FORMS, exist_ok=True)
    return sorted((n for n in os.listdir(FORMS) if n.lower().endswith(".json")), key=str.lower)


def active_name():
    name = os.path.basename(str(read_json(ACTIVE, {}).get("activa", "")))
    available = forms()
    return name if name in available else (available[0] if available else "")


def set_active(name):
    name = os.path.basename(name or "")
    if name not in forms(): raise ValueError("La configuración no existe.")
    with _lock: write_json(ACTIVE, {"activa": name})


def favorite_names():
    data, available = read_json(FAVORITES, {}), set(forms())
    a = os.path.basename(str(data.get("favorito_1", "")))
    b = os.path.basename(str(data.get("favorito_2", "")))
    return (a if a in available else "", b if b in available else "")


def toggle(icon=None):
    with _lock:
        a, b = favorite_names()
        if not a or not b or a == b:
            msg = "Defina dos favoritas distintas en Crear configuraciones."
            core.guardar_log("⚠️ " + msg)
            try: icon.notify(msg, "DMS - Configuraciones")
            except Exception: pass
            return
        target = b if active_name() == a else a
        set_active(target)
        core.guardar_log(f"✅ Configuración activa: {target}")
        try: icon.notify(f"Configuración activa: {os.path.splitext(target)[0]}", "DMS - Cambio rápido")
        except Exception: pass


def initialize():
    migrate()
    if not os.path.exists(DEFAULT_FORM):
        write_json(DEFAULT_FORM, {"nombre":"Formulario Visitantes","campos":[
            {"dato":"Primer Apellido","tabuladores":0},{"dato":"Nombre","tabuladores":0},
            {"dato":"Cedula","tabuladores":1},{"dato":"Fecha de Nacimiento","tabuladores":2}]})
    if not os.path.exists(ACTIVE): set_active(forms()[0])
    if not os.path.exists(FAVORITES): write_json(FAVORITES, {"favorito_1":"","favorito_2":"","atajo":HOTKEY})


def load_active():
    try:
        with open(os.path.join(FORMS, active_name()), "r", encoding="utf-8") as f: return json.load(f)
    except Exception as e: core.guardar_log(f"⚠️ Error cargando configuración: {e}"); return None


def load_last_com():
    value = str(read_json(LAST_COM, {}).get("puerto", "")).strip()
    return value or None


def save_last_com(port):
    write_json(LAST_COM, {"puerto": str(port).strip(), "fecha": datetime.now().isoformat()})


class ConfigSelector:
    def __init__(self, parent=None):
        self.win = Toplevel(parent) if parent else Tk(); self.win.title("Seleccionar configuración")
        self.win.geometry("460x275"); self.win.resizable(False, False); self.win.configure(bg=core.COLOR_BG)
        try: self.win.iconbitmap(default=core.ICON_ASSETS_PATH)
        except Exception: pass
        s=ttk.Style(self.win); s.theme_use("clam"); s.configure("X.TFrame",background=core.COLOR_BG)
        s.configure("X.TLabel",background=core.COLOR_BG,foreground="white",font=("Segoe UI",11))
        s.configure("X.TButton",background=core.COLOR_ACCENT,foreground="white",font=("Segoe UI",10,"bold"),padding=7)
        f=ttk.Frame(self.win,padding=22,style="X.TFrame"); f.pack(fill="both",expand=True)
        ttk.Label(f,text="Seleccione la configuración activa:",style="X.TLabel").pack(anchor="w",pady=(8,8))
        available=forms()
        if not available: messagebox.showerror("Sin configuraciones","No hay formularios disponibles.",parent=self.win); self.win.destroy(); return
        self.combo=ttk.Combobox(f,values=available,state="readonly",width=48); self.combo.pack(fill="x",pady=(0,12)); self.combo.set(active_name())
        a,b=favorite_names(); ttk.Label(f,text=f"Favoritas: {a or 'sin definir'} ↔ {b or 'sin definir'}\nAtajo: {HOTKEY}",style="X.TLabel").pack(anchor="w",pady=(0,15))
        ttk.Button(f,text="Activar",style="X.TButton",command=self.save).pack()
        self.win.grab_set(); self.win.focus_force(); self.win.wait_window()
    def save(self):
        try: set_active(self.combo.get()); self.win.destroy()
        except Exception as e: messagebox.showerror("Error",str(e),parent=self.win)


def patch_core():
    core.VERSION=VERSION; core.CONFIG_DIR=FORMS; core.CONFIG_ACTUAL=ACTIVE; core.CONFIG_DEFECTO=DEFAULT_FORM; core.LAST_COM_FILE=LAST_COM
    # El pegado Unicode ya conserva Ñ y tildes. Desactivar los campos críticos evita
    # que Ctrl+A vuelva a seleccionar y reemplace el apellido recién escrito.
    core.CRITICAL_FIELDS = set()
    core.SelectorConfiguracionGUI=ConfigSelector; core.inicializar_configuracion=initialize
    core.cargar_configuracion_activa=load_active; core.cargar_ultimo_com=load_last_com; core.guardar_ultimo_com=save_last_com


def hotkey_loop(icon):
    global _hotkey_tid
    if os.name != "nt": return
    import ctypes.wintypes
    u32,k32=ctypes.windll.user32,ctypes.windll.kernel32; _hotkey_tid=k32.GetCurrentThreadId()
    if not u32.RegisterHotKey(None,0xD35,0x0001|0x0002|0x4000,ord("C")):
        core.guardar_log(f"⚠️ No se pudo registrar {HOTKEY}"); return
    try:
        msg=ctypes.wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg),None,0,0)>0:
            if msg.message==0x0312 and msg.wParam==0xD35: toggle(icon)
    finally: u32.UnregisterHotKey(None,0xD35)


def stop_hotkey():
    if os.name=="nt" and _hotkey_tid:
        try: ctypes.windll.user32.PostThreadMessageW(_hotkey_tid,0x0012,0,0)
        except Exception: pass


def run():
    patch_core(); core.ensure_single_instance(); core.validar_licencia(); initialize()
    selected=[]
    while not selected:
        root=Tk(); root.title(f"Calibrando lector QR - v{VERSION}"); root.configure(bg=core.COLOR_BG)
        label=ttk.Label(root,text="Inicializando...",font=("Segoe UI",12)); label.pack(padx=30,pady=30)
        def status(text):
            try: label.config(text=text); root.update()
            except Exception: pass
        def calibrate():
            last=load_last_com(); port=last if last and core.puerto_responde(last,status,segundos=3) else core.encontrar_lector_qr_por_actividad(status)
            if port: save_last_com(port); selected.append(port)
            try: root.after(0,root.destroy)
            except Exception: pass
        threading.Thread(target=calibrate,daemon=True).start(); root.mainloop()
        if not selected:
            x=Tk(); x.withdraw(); retry=messagebox.askretrycancel("No se detectó lector","No se detectó el lector QR.\n\n¿Intentar nuevamente?",parent=x); x.destroy()
            if not retry: return
    root=Tk(); root.withdraw(); ConfigSelector(root); root.destroy(); core.ocultar_consola()
    threading.Thread(target=core.escuchar_en_segundo_plano,args=(selected[0],),daemon=True).start()
    def exit_app(icon,item=None): stop_hotkey(); icon.stop(); os._exit(0)
    def choose(icon,item=None):
        def open_ui():
            try: r=Tk(); r.withdraw(); ConfigSelector(r); r.destroy()
            except Exception as e: core.guardar_log(f"⚠️ Error abriendo selector: {e}")
        threading.Thread(target=open_ui,daemon=True).start()
    image=core.cargar_icono(); icon=core.TrayIcon("DMS_QR",image,"DMS - Lector QR",menu=core.TrayMenu(
        core.TrayMenuItem(f"Alternar favoritas ({HOTKEY})",lambda i,x=None:toggle(i)),
        core.TrayMenuItem("Cambiar configuración",choose),core.TrayMenuItem("Salir",exit_app)))
    threading.Thread(target=hotkey_loop,args=(icon,),daemon=True).start(); icon.run()

if __name__ == "__main__": run()
