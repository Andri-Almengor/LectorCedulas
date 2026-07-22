import os
import threading
from tkinter import Tk, messagebox, ttk

from assets.runtime import dms_config_runtime as config
from assets.runtime import dms_reader_runtime as reader
from assets.runtime import dms_session_runtime as session
from assets.runtime import lector_core as core


VERSION = "3.9.0"
HOTKEY = "Ctrl+Alt+C"


def toggle_configuration(icon=None):
    if session.STOP.is_set():
        return

    first, second = config.favorite_names()
    if not first or not second or first == second:
        message = "Defina dos favoritas distintas en Crear configuraciones."
        session.log("⚠️ " + message)
        try:
            icon.notify(message, "DMS - Configuraciones")
        except Exception:
            pass
        return

    target = second if config.active_name() == first else first
    config.set_active(target)
    session.log(f"✅ Configuración activa: {target}")
    try:
        icon.notify(
            f"Configuración activa: {os.path.splitext(target)[0]}",
            "DMS - Cambio rápido",
        )
    except Exception:
        pass


def patch_core():
    core.VERSION = VERSION
    core.CONFIG_DIR = config.FORMS
    core.CONFIG_ACTUAL = config.ACTIVE
    core.CONFIG_DEFECTO = config.DEFAULT_FORM
    core.LAST_COM_FILE = config.LAST_COM

    # El pegado Unicode conserva Ñ y tildes sin volver a seleccionar el campo.
    core.CRITICAL_FIELDS = set()

    # Ritmo conservador para no saturar aplicaciones de formularios lentas.
    core.pyautogui.PAUSE = 0.035
    core.TAB_PAUSE = 0.06
    core.BETWEEN_FIELDS = 0.14

    core.SelectorConfiguracionGUI = config.ConfigSelector
    core.inicializar_configuracion = config.initialize
    core.cargar_configuracion_activa = config.load_active
    core.cargar_ultimo_com = config.load_last_com
    core.guardar_ultimo_com = config.save_last_com
    core.puerto_responde = reader.port_responds
    core.encontrar_lector_qr_por_actividad = reader.find_reader
    core._esperar_serial_silencioso = reader.wait_serial_silent
    core._leer_buffer_serial = reader.read_serial_buffer
    core.escribir_con_configuracion = reader.write_form
    core.escuchar_en_segundo_plano = (
        lambda port: reader.serial_listener(port, config.load_active)
    )


def calibration_window():
    selected = []
    root = Tk()
    root.title(f"Calibrando lector QR - v{VERSION}")
    root.configure(bg=core.COLOR_BG)
    root.protocol(
        "WM_DELETE_WINDOW",
        lambda: session.shutdown("Se cerró la ventana de calibración"),
    )

    try:
        root.iconbitmap(default=core.ICON_ASSETS_PATH)
    except Exception:
        pass

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        "Calibration.TLabel",
        background=core.COLOR_BG,
        foreground=core.COLOR_TEXT,
        font=("Segoe UI", 12),
    )
    status_label = ttk.Label(
        root,
        text="Inicializando...",
        style="Calibration.TLabel",
    )
    status_label.pack(padx=30, pady=30)

    def update_status(text):
        try:
            root.after(0, lambda value=text: status_label.config(text=value))
        except Exception:
            pass

    def worker():
        try:
            last_port = config.load_last_com()
            if last_port and reader.port_responds(last_port, update_status, 3):
                selected.append(last_port)
            elif not session.STOP.is_set():
                detected = reader.find_reader(update_status)
                if detected:
                    config.save_last_com(detected)
                    selected.append(detected)
        finally:
            try:
                root.after(0, root.destroy)
            except Exception:
                pass

    threading.Thread(
        target=worker,
        name="DMSCalibration",
        daemon=True,
    ).start()
    root.mainloop()
    return selected[0] if selected else None


def detect_reader():
    while not session.STOP.is_set():
        port = calibration_window()
        if port:
            return port
        if session.STOP.is_set():
            return None

        dialog = Tk()
        dialog.withdraw()
        dialog.attributes("-topmost", True)
        retry = messagebox.askretrycancel(
            "No se detectó lector",
            "No se detectó el lector QR.\n\n¿Intentar nuevamente?",
            parent=dialog,
        )
        dialog.destroy()

        if not retry:
            session.shutdown("Se canceló la detección del lector")
    return None


def open_selector(icon=None, item=None):
    config.open_selector(session.STOP, hotkey=HOTKEY)


def run():
    patch_core()
    session.configure_logger(core.guardar_log)
    session.set_low_resource_mode()

    if not session.ensure_single_instance():
        return

    session.start_watchers()

    # Mantiene el comportamiento de licencia existente del proyecto.
    core.validar_licencia()
    config.initialize(HOTKEY)

    port = detect_reader()
    if not port or session.STOP.is_set():
        return

    root = Tk()
    root.withdraw()
    config.ConfigSelector(root, stop_event=session.STOP, hotkey=HOTKEY)
    root.destroy()

    if session.STOP.is_set():
        return

    core.ocultar_consola()
    threading.Thread(
        target=reader.serial_listener,
        args=(port, config.load_active),
        name="DMSSerialListener",
        daemon=True,
    ).start()

    image = core.cargar_icono()
    tray_icon = core.TrayIcon(
        "DMS_QR",
        image,
        "DMS - Lector QR",
        menu=core.TrayMenu(
            core.TrayMenuItem(
                f"Alternar favoritas ({HOTKEY})",
                lambda icon, item=None: toggle_configuration(icon),
            ),
            core.TrayMenuItem("Cambiar configuración", open_selector),
            core.TrayMenuItem(
                "Salir",
                lambda icon, item=None: session.shutdown(
                    "Salida desde la bandeja",
                    icon,
                ),
            ),
        ),
    )
    session.set_tray_icon(tray_icon)

    threading.Thread(
        target=session.hotkey_loop,
        args=(toggle_configuration, tray_icon),
        name="DMSHotkey",
        daemon=True,
    ).start()
    tray_icon.run()


if __name__ == "__main__":
    run()
