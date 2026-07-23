from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from .reader_calibration import CalibrationProgress, CalibrationResult
from .ui_theme import COLOR_MUTED, apply_dms_theme, apply_window_icon


@dataclass(frozen=True, slots=True)
class ControlPanelSnapshot:
    reader_state: str
    port: str
    configuration: str
    profile: str
    queue_count: int
    queue_paused: bool
    last_success: str
    last_error: str


@dataclass(frozen=True, slots=True)
class ControlPanelActions:
    calibrate: Callable[[], None]
    reconnect: Callable[[], None]
    change_configuration: Callable[[], None]
    toggle_favorites: Callable[[], None]
    pause: Callable[[], None]
    resume: Callable[[], None]
    cancel_current: Callable[[], None]
    clear_queue: Callable[[], None]
    open_logs: Callable[[], None]
    open_diagnostics: Callable[[], None]
    clear_diagnostics: Callable[[], None]
    shutdown: Callable[[], None]


def _center(root: tk.Tk, width: int, height: int) -> None:
    root.update_idletasks()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")


def run_calibration_dialog(
    *,
    product_name: str,
    icon_path: str | Path | None,
    ports_provider: Callable[[], list[str]],
    preferred_device: str,
    calibrate: Callable[
        [str | None, threading.Event, Callable[[CalibrationProgress], None]],
        CalibrationResult,
    ],
) -> bool:
    root = tk.Tk()
    root.title(f"{product_name} - Calibrar lector")
    root.resizable(False, False)
    apply_dms_theme(root)
    apply_window_icon(root, icon_path)
    _center(root, 650, 430)

    result = {"success": False}
    worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
    cancel_event = threading.Event()
    running = {"value": False}

    outer = ttk.Frame(root, style="DMS.TFrame", padding=22)
    outer.pack(fill="both", expand=True)

    ttk.Label(outer, text="Calibración del lector", style="DMS.Header.TLabel").pack(anchor="w")
    ttk.Label(
        outer,
        text=(
            "Seleccione el puerto inicial y pase una cédula por el lector. "
            "Cada puerto se probará durante 10 segundos antes de continuar con el siguiente."
        ),
        style="DMS.Sub.TLabel",
        wraplength=595,
        justify="left",
    ).pack(anchor="w", pady=(4, 18))

    card = ttk.Frame(outer, style="DMS.Panel.TFrame", padding=16)
    card.pack(fill="x")

    ttk.Label(card, text="Puerto inicial", style="DMS.Panel.TLabel").grid(row=0, column=0, sticky="w")
    port_var = tk.StringVar()
    combo = ttk.Combobox(card, textvariable=port_var, state="readonly", style="DMS.TCombobox", width=32)
    combo.grid(row=1, column=0, sticky="ew", pady=(5, 12), padx=(0, 10))

    status_var = tk.StringVar(value="Listo para iniciar.")
    detail_var = tk.StringVar(value="El último COM guardado se selecciona automáticamente.")
    ttk.Label(card, textvariable=status_var, style="DMS.Panel.TLabel", font=("Segoe UI", 11, "bold")).grid(
        row=2,
        column=0,
        columnspan=2,
        sticky="w",
    )
    ttk.Label(
        card,
        textvariable=detail_var,
        style="DMS.Panel.TLabel",
        foreground=COLOR_MUTED,
        wraplength=570,
        justify="left",
    ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(3, 12))

    progressbar = ttk.Progressbar(card, mode="determinate", maximum=100, style="DMS.Horizontal.TProgressbar")
    progressbar.grid(row=4, column=0, columnspan=2, sticky="ew")
    card.columnconfigure(0, weight=1)

    buttons = ttk.Frame(outer, style="DMS.TFrame")
    buttons.pack(fill="x", pady=(18, 0))
    calibrate_button = ttk.Button(buttons, text="Calibrar lector", style="DMS.Primary.TButton")
    calibrate_button.pack(side="left")
    close_button = ttk.Button(buttons, text="Cerrar aplicación", style="DMS.Ghost.TButton")
    close_button.pack(side="right")

    def refresh_ports() -> list[str]:
        try:
            values = ports_provider()
        except Exception:
            values = []
        combo["values"] = values
        if preferred_device and preferred_device in values:
            port_var.set(preferred_device)
        elif port_var.get() in values:
            pass
        elif values:
            port_var.set(values[0])
        else:
            port_var.set("")
        return values

    def post_progress(value: CalibrationProgress) -> None:
        worker_queue.put(("progress", value))

    def worker(selected: str | None) -> None:
        calibration_result = calibrate(selected, cancel_event, post_progress)
        worker_queue.put(("result", calibration_result))

    def start_calibration() -> None:
        if running["value"]:
            return
        ports = refresh_ports()
        if not ports:
            retry = messagebox.askretrycancel(
                "Sin puertos COM",
                "No se encontraron puertos COM. Conecte el lector y pulse Reintentar, o Cancelar para cerrar.",
                parent=root,
            )
            if retry:
                root.after(200, start_calibration)
            else:
                root.destroy()
            return
        running["value"] = True
        cancel_event.clear()
        calibrate_button.configure(state="disabled")
        combo.configure(state="disabled")
        status_var.set("Buscando lector…")
        detail_var.set("Pase una cédula por el lector cuando se indique el puerto.")
        progressbar["value"] = 0
        threading.Thread(
            target=worker,
            args=(port_var.get() or None,),
            name="DMSCalibrationWorker",
            daemon=True,
        ).start()

    def close() -> None:
        cancel_event.set()
        result["success"] = False
        root.destroy()

    calibrate_button.configure(command=start_calibration)
    close_button.configure(command=close)
    root.protocol("WM_DELETE_WINDOW", close)

    def poll_worker() -> None:
        try:
            while True:
                kind, payload = worker_queue.get_nowait()
                if kind == "progress" and isinstance(payload, CalibrationProgress):
                    status_var.set(f"Probando {payload.device} ({payload.index}/{payload.total})")
                    detail_var.set(payload.detail)
                    elapsed = max(0.0, min(10.0, 10.0 - payload.remaining_seconds))
                    progressbar["value"] = elapsed * 10.0
                elif kind == "result" and isinstance(payload, CalibrationResult):
                    running["value"] = False
                    calibrate_button.configure(state="normal")
                    combo.configure(state="readonly")
                    if payload.success:
                        result["success"] = True
                        status_var.set("Lector calibrado correctamente")
                        detail_var.set(payload.message)
                        progressbar["value"] = 100
                        messagebox.showinfo("Calibración completa", payload.message, parent=root)
                        root.destroy()
                        return
                    retry = messagebox.askretrycancel(
                        "Lector no detectado",
                        f"{payload.message}\n\n¿Desea volver a intentarlo?",
                        parent=root,
                    )
                    if retry:
                        refresh_ports()
                        root.after(200, start_calibration)
                    else:
                        close()
                        return
        except queue.Empty:
            pass
        if root.winfo_exists():
            root.after(80, poll_worker)

    refresh_ports()
    root.after(80, poll_worker)
    root.mainloop()
    return bool(result["success"])


def run_configuration_selector(
    *,
    icon_path: str | Path | None,
    forms_provider: Callable[[], list[str]],
    active_provider: Callable[[], str],
    activate: Callable[[str], None],
) -> None:
    root = tk.Tk()
    root.title("DMS - Seleccionar configuración")
    root.resizable(False, False)
    apply_dms_theme(root)
    apply_window_icon(root, icon_path)
    _center(root, 570, 260)

    frame = ttk.Frame(root, style="DMS.TFrame", padding=22)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Cambiar configuración", style="DMS.Header.TLabel").pack(anchor="w")
    ttk.Label(
        frame,
        text="Seleccione el formulario que se utilizará en las próximas lecturas.",
        style="DMS.Sub.TLabel",
    ).pack(anchor="w", pady=(4, 16))

    values = forms_provider()
    combo = ttk.Combobox(frame, values=values, state="readonly", style="DMS.TCombobox", width=58)
    combo.pack(fill="x")
    active = active_provider()
    if active in values:
        combo.set(active)
    elif values:
        combo.set(values[0])

    def confirm() -> None:
        selected = combo.get().strip()
        if not selected:
            messagebox.showwarning("Sin selección", "Seleccione una configuración.", parent=root)
            return
        try:
            activate(selected)
        except Exception as exc:
            messagebox.showerror("Configuración inválida", str(exc), parent=root)
            return
        root.destroy()

    ttk.Button(frame, text="Activar configuración", style="DMS.Primary.TButton", command=confirm).pack(
        anchor="e",
        pady=(18, 0),
    )
    root.mainloop()


def run_control_panel(
    *,
    product_name: str,
    version: str,
    icon_path: str | Path | None,
    snapshot_provider: Callable[[], ControlPanelSnapshot],
    actions: ControlPanelActions,
) -> None:
    root = tk.Tk()
    root.title(f"{product_name} {version}")
    root.resizable(False, False)
    apply_dms_theme(root)
    apply_window_icon(root, icon_path)
    _center(root, 760, 600)

    outer = ttk.Frame(root, style="DMS.TFrame", padding=20)
    outer.pack(fill="both", expand=True)

    ttk.Label(outer, text=product_name, style="DMS.Header.TLabel").pack(anchor="w")
    ttk.Label(
        outer,
        text=f"Panel de control del lector • versión {version}",
        style="DMS.Sub.TLabel",
    ).pack(anchor="w", pady=(3, 14))

    status_card = ttk.Frame(outer, style="DMS.Panel.TFrame", padding=15)
    status_card.pack(fill="x")

    reader_var = tk.StringVar()
    config_var = tk.StringVar()
    queue_var = tk.StringVar()
    success_var = tk.StringVar()
    error_var = tk.StringVar()

    ttk.Label(status_card, textvariable=reader_var, style="DMS.Panel.TLabel", font=("Segoe UI", 11, "bold")).pack(
        anchor="w"
    )
    ttk.Label(status_card, textvariable=config_var, style="DMS.Panel.TLabel").pack(anchor="w", pady=(4, 0))
    ttk.Label(status_card, textvariable=queue_var, style="DMS.Panel.TLabel").pack(anchor="w", pady=(4, 0))
    ttk.Label(status_card, textvariable=success_var, style="DMS.Panel.TLabel").pack(anchor="w", pady=(4, 0))
    ttk.Label(
        status_card,
        textvariable=error_var,
        style="DMS.Panel.TLabel",
        foreground="#ffb4ab",
        wraplength=690,
        justify="left",
    ).pack(anchor="w", pady=(4, 0))

    ttk.Label(outer, text="Lector", style="DMS.TLabel", font=("Segoe UI", 11, "bold")).pack(
        anchor="w",
        pady=(18, 8),
    )
    reader_actions = ttk.Frame(outer, style="DMS.TFrame")
    reader_actions.pack(fill="x")
    ttk.Button(
        reader_actions,
        text="Calibrar lector",
        style="DMS.Primary.TButton",
        command=actions.calibrate,
    ).pack(side="left")
    ttk.Button(
        reader_actions,
        text="Reconectar",
        style="DMS.Ghost.TButton",
        command=actions.reconnect,
    ).pack(side="left", padx=8)
    ttk.Button(
        reader_actions,
        text="Cambiar configuración",
        style="DMS.Ghost.TButton",
        command=actions.change_configuration,
    ).pack(side="left")
    ttk.Button(
        reader_actions,
        text="Alternar favoritas",
        style="DMS.Ghost.TButton",
        command=actions.toggle_favorites,
    ).pack(side="left", padx=8)

    ttk.Label(outer, text="Escrituras", style="DMS.TLabel", font=("Segoe UI", 11, "bold")).pack(
        anchor="w",
        pady=(18, 8),
    )
    write_actions = ttk.Frame(outer, style="DMS.TFrame")
    write_actions.pack(fill="x")
    ttk.Button(write_actions, text="Pausar", style="DMS.Ghost.TButton", command=actions.pause).pack(side="left")
    ttk.Button(write_actions, text="Reanudar", style="DMS.Ghost.TButton", command=actions.resume).pack(
        side="left",
        padx=8,
    )
    ttk.Button(
        write_actions,
        text="Cancelar actual",
        style="DMS.Ghost.TButton",
        command=actions.cancel_current,
    ).pack(side="left")
    ttk.Button(
        write_actions,
        text="Vaciar cola",
        style="DMS.Ghost.TButton",
        command=actions.clear_queue,
    ).pack(side="left", padx=8)

    ttk.Label(outer, text="Diagnóstico", style="DMS.TLabel", font=("Segoe UI", 11, "bold")).pack(
        anchor="w",
        pady=(18, 8),
    )
    diagnostic_actions = ttk.Frame(outer, style="DMS.TFrame")
    diagnostic_actions.pack(fill="x")
    ttk.Button(
        diagnostic_actions,
        text="Abrir logs",
        style="DMS.Ghost.TButton",
        command=actions.open_logs,
    ).pack(side="left")
    ttk.Button(
        diagnostic_actions,
        text="Abrir diagnósticos",
        style="DMS.Ghost.TButton",
        command=actions.open_diagnostics,
    ).pack(side="left", padx=8)
    ttk.Button(
        diagnostic_actions,
        text="Borrar diagnósticos",
        style="DMS.Ghost.TButton",
        command=actions.clear_diagnostics,
    ).pack(side="left")

    footer = ttk.Frame(outer, style="DMS.TFrame")
    footer.pack(fill="x", side="bottom", pady=(20, 0))
    ttk.Label(
        footer,
        text="El menú de la bandeja usa el estilo nativo de Windows; este panel utiliza la identidad visual DMS.",
        style="DMS.Sub.TLabel",
    ).pack(side="left")

    def exit_application() -> None:
        actions.shutdown()
        root.destroy()

    ttk.Button(
        footer,
        text="Salir",
        style="DMS.Primary.TButton",
        command=exit_application,
    ).pack(side="right")

    def refresh() -> None:
        try:
            snapshot = snapshot_provider()
            reader_var.set(f"Lector: {snapshot.reader_state} | {snapshot.port}")
            config_var.set(f"Configuración: {snapshot.configuration} | {snapshot.profile}")
            queue_state = "pausada" if snapshot.queue_paused else "activa"
            queue_var.set(f"Cola: {snapshot.queue_count} | {queue_state}")
            success_var.set(f"Última lectura aceptada: {snapshot.last_success}")
            error_var.set(f"Último error: {snapshot.last_error}")
        except Exception:
            reader_var.set("Lector: estado no disponible")
        if root.winfo_exists():
            root.after(500, refresh)

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    refresh()
    root.mainloop()
