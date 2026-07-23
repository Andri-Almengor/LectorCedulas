from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

COLOR_BG = "#212121"
COLOR_PANEL = "#2a2a2a"
COLOR_INPUT = "#1e1e1e"
COLOR_TEXT = "#ffffff"
COLOR_MUTED = "#cfcfcf"
COLOR_ACCENT = "#e53935"
COLOR_ACCENT_ACTIVE = "#c62828"
COLOR_SUCCESS = "#43a047"
COLOR_WARNING = "#f9a825"


def apply_dms_theme(root: tk.Misc) -> ttk.Style:
    """Aplica la misma paleta visual usada por el dashboard DMS."""

    try:
        root.configure(bg=COLOR_BG)
    except tk.TclError:
        pass

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure("DMS.TFrame", background=COLOR_BG)
    style.configure("DMS.Panel.TFrame", background=COLOR_PANEL)
    style.configure("DMS.TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=("Segoe UI", 10))
    style.configure("DMS.Panel.TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT, font=("Segoe UI", 10))
    style.configure("DMS.Header.TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=("Segoe UI", 18, "bold"))
    style.configure("DMS.Sub.TLabel", background=COLOR_BG, foreground=COLOR_MUTED, font=("Segoe UI", 10))
    style.configure(
        "DMS.Primary.TButton",
        background=COLOR_ACCENT,
        foreground=COLOR_TEXT,
        font=("Segoe UI", 10, "bold"),
        padding=(12, 8),
    )
    style.map("DMS.Primary.TButton", background=[("active", COLOR_ACCENT_ACTIVE), ("disabled", "#5a2b2b")])
    style.configure(
        "DMS.Ghost.TButton",
        background=COLOR_PANEL,
        foreground=COLOR_TEXT,
        font=("Segoe UI", 10),
        padding=(12, 8),
    )
    style.map("DMS.Ghost.TButton", background=[("active", "#363636"), ("disabled", "#262626")])
    style.configure(
        "DMS.TCombobox",
        fieldbackground=COLOR_INPUT,
        background=COLOR_INPUT,
        foreground=COLOR_TEXT,
        arrowcolor=COLOR_TEXT,
        padding=6,
    )
    style.map(
        "DMS.TCombobox",
        fieldbackground=[("readonly", COLOR_INPUT)],
        foreground=[("readonly", COLOR_TEXT)],
        selectbackground=[("readonly", COLOR_ACCENT)],
        selectforeground=[("readonly", COLOR_TEXT)],
    )
    style.configure(
        "DMS.Horizontal.TProgressbar",
        troughcolor=COLOR_INPUT,
        background=COLOR_ACCENT,
        lightcolor=COLOR_ACCENT,
        darkcolor=COLOR_ACCENT,
        bordercolor=COLOR_PANEL,
    )
    style.configure("DMS.TSeparator", background="#4a4a4a")
    return style


def apply_window_icon(root: tk.Misc, icon_path: str | Path | None) -> None:
    if not icon_path:
        return
    path = Path(icon_path)
    if not path.is_file():
        return
    try:
        root.iconbitmap(default=str(path))
    except (tk.TclError, OSError):
        return
