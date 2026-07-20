import os
import sys
import json
import tkinter as tk
from tkinter import ttk, messagebox, StringVar, IntVar
try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

CONFIG_DIR = "configs"

ICON_CANDIDATES = [
    os.path.join(os.path.dirname(sys.argv[0]), "assets", "DMS_icono_circulo_i.ico"),
    os.path.join(os.path.dirname(sys.argv[0]), "DMS_icono_circulo_i.ico"),
    "/mnt/data/DMS_icono_circulo_i.ico",
]

COLOR_BG = "#212121"
COLOR_TEXT = "white"
COLOR_ACCENT = "#e53935"
COLOR_PANEL = "#2a2a2a"

DEFAULT_FIELDS = [
    {"dato": "Apellidos",           "tabuladores": 0},  # <— unificado
    {"dato": "Nombre",              "tabuladores": 0},
    {"dato": "Cedula",              "tabuladores": 0},
    {"dato": "Sexo",                "tabuladores": 0},
    {"dato": "Fecha de Nacimiento", "tabuladores": 0},
    {"dato": "Fecha de Expiracion", "tabuladores": 0},
]


# -----------------------------
# Ventana 2 (crear/editar)
# -----------------------------
class EditorConfig(tk.Toplevel):
    def __init__(self, master, modo="crear", nombre_existente=None):
        super().__init__(master)
        self.modo = modo                    # "crear" | "editar"
        self.nombre_original = None         # sin .json cuando se edita
        self.title("Crear configuración" if modo == "crear" else "Editar configuración")
        self.geometry("1100x600")
        self.minsize(1000, 560)
        self.configure(bg=COLOR_BG)
        self._apply_icon()

        # Datos
        self.campos = [dict(x) for x in DEFAULT_FIELDS]

        # Estilos
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=COLOR_BG)
        style.configure("Panel.TFrame", background=COLOR_PANEL)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=("Segoe UI", 11))
        style.configure("TEntry", fieldbackground="white", background="white", foreground="black",
                        relief="flat", font=("Segoe UI", 11))
        style.configure("TButton", font=("Segoe UI", 11), padding=6, background=COLOR_ACCENT, foreground="white")
        style.map("TButton", background=[('active', '#d32f2f')])
        style.configure("Danger.TButton", background="#c62828", foreground="white")
        style.map("Danger.TButton", background=[('active', '#b71c1c')])
        style.configure("TCombobox", fieldbackground="white", background="white", foreground="black")

        # Grid raíz
        self.grid_rowconfigure(0, weight=0)   # nombre
        self.grid_rowconfigure(1, weight=1)   # split
        self.grid_rowconfigure(2, weight=0)   # footer
        self.grid_columnconfigure(0, weight=1)

        # Nombre
        name_wrap = ttk.Frame(self, padding=(16, 10), style="TFrame")
        name_wrap.grid(row=0, column=0, sticky="ew")
        name_wrap.grid_columnconfigure(0, weight=1)
        name_wrap.grid_columnconfigure(1, weight=0)
        self._add_logo_header(name_wrap)
        ttk.Label(name_wrap, text="Nombre de la configuración:", style="TLabel").grid(row=0, column=0, sticky="w")
        self.entry_nombre = ttk.Entry(name_wrap, width=45, style="TEntry")
        self.entry_nombre.grid(row=1, column=0, sticky="w", pady=(4, 8))

        # Split
        split = ttk.Frame(self, padding=(16, 8), style="TFrame")
        split.grid(row=1, column=0, sticky="nsew")
        split.grid_columnconfigure(0, weight=62, uniform="split")
        split.grid_columnconfigure(1, weight=38, uniform="split")
        split.grid_rowconfigure(0, weight=1)

        left = ttk.Frame(split, style="Panel.TFrame", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,8))
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        right = ttk.Frame(split, style="Panel.TFrame", padding=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(8,0))
        right.grid_columnconfigure(0, weight=1)

        # Lista de campos
        ttk.Label(left, text="Campos (orden):", style="TLabel").grid(row=0, column=0, sticky="w")
        lb_frame = ttk.Frame(left, style="Panel.TFrame")
        lb_frame.grid(row=1, column=0, sticky="nsew", pady=(6,6))
        lb_frame.grid_rowconfigure(0, weight=1)
        lb_frame.grid_columnconfigure(0, weight=1)

        self.lb = tk.Listbox(lb_frame, activestyle="dotbox", selectmode="browse",
                             bg="white", fg="black", font=("Segoe UI", 11), relief="flat")
        self.lb.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(lb_frame, orient="vertical", command=self.lb.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.lb.config(yscrollcommand=sb.set)
        self.lb.bind("<<ListboxSelect>>", self.on_lb_select)

        order_bar = ttk.Frame(left, style="Panel.TFrame")
        order_bar.grid(row=2, column=0, sticky="ew", pady=(4,0))
        ttk.Button(order_bar, text="↑ Subir", command=self.move_up).pack(side="left")
        ttk.Button(order_bar, text="↓ Bajar", command=self.move_down).pack(side="left", padx=6)
        ttk.Button(order_bar, text="+ Duplicar", command=self.dup_field).pack(side="left", padx=(6,0))
        ttk.Button(order_bar, text="🗑 Eliminar", style="Danger.TButton", command=self.delete_field).pack(side="right")

        # Editor de campo
        ttk.Label(right, text="Editar campo:", style="TLabel").grid(row=0, column=0, sticky="w")
        editor = ttk.Frame(right, style="Panel.TFrame")
        editor.grid(row=1, column=0, sticky="nw", pady=(8,2))
        ttk.Label(editor, text="Texto del campo (dato):", style="TLabel").grid(row=0, column=0, sticky="w")
        self.var_dato = StringVar()
        self.ent_dato = ttk.Entry(editor, textvariable=self.var_dato, width=35, style="TEntry")
        self.ent_dato.grid(row=1, column=0, sticky="w", pady=(4,10))
        ttk.Label(editor, text="Tabuladores:", style="TLabel").grid(row=2, column=0, sticky="w")
        self.var_tabs = IntVar(value=0)
        self.spn_tabs = tk.Spinbox(editor, from_=0, to=50, textvariable=self.var_tabs,
                                   width=7, relief="flat", font=("Segoe UI", 11))
        self.spn_tabs.grid(row=3, column=0, sticky="w", pady=(4,10))

        actions = ttk.Frame(right, style="Panel.TFrame")
        actions.grid(row=2, column=0, sticky="w", pady=(6,0))
        ttk.Button(actions, text="Aplicar cambios al campo", command=self.apply_field_changes).pack(side="left")

        # Footer
        footer = ttk.Frame(self, padding=(16, 8), style="TFrame")
        footer.grid(row=2, column=0, sticky="ew")
        self.btn_guardar = ttk.Button(
            footer,
            text=("Crear nueva" if self.modo == "crear" else "Guardar cambios"),
            command=self.guardar_config
        )
        self.btn_guardar.pack(side="left")

        # Inicializa lista y carga si es edición
        self.refresh_listbox()
        self.select_index(0)

        if self.modo == "editar" and nombre_existente:
            self._cargar_existente(nombre_existente)

    # Helpers UI
    def _apply_icon(self):
        for p in ICON_CANDIDATES:
            try:
                if os.path.exists(p):
                    self.iconbitmap(default=p); return
            except Exception:
                pass

    def _add_logo_header(self, parent):
        try:
            if not Image or not ImageTk:
                return
            for p in ICON_CANDIDATES:
                if os.path.exists(p):
                    img = Image.open(p).resize((48, 48))
                    self._logo_ref = ImageTk.PhotoImage(img)
                    ttk.Label(parent, image=self._logo_ref, background=COLOR_BG).grid(row=0, column=1, sticky="e")
                    return
        except Exception:
            pass

    def current_index(self):
        sel = self.lb.curselection()
        return sel[0] if sel else None

    def refresh_listbox(self):
        self.lb.delete(0, tk.END)
        for c in self.campos:
            self.lb.insert(tk.END, f"{c['dato']}")

    def select_index(self, idx):
        if not self.campos: return
        idx = max(0, min(idx, len(self.campos)-1))
        self.lb.selection_clear(0, tk.END)
        self.lb.selection_set(idx)
        self.lb.activate(idx)
        self.lb.see(idx)
        self.load_editor_from_index(idx)

    def on_lb_select(self, event=None):
        idx = self.current_index()
        if idx is not None:
            self.load_editor_from_index(idx)

    def load_editor_from_index(self, idx):
        c = self.campos[idx]
        self.var_dato.set(c["dato"])
        self.var_tabs.set(int(c["tabuladores"]))

    # Edición de campos
    def apply_field_changes(self):
        idx = self.current_index()
        if idx is None: return
        nombre = (self.var_dato.get() or "").strip() or "Sin nombre"
        try:
            tabs = int(self.var_tabs.get())
        except Exception:
            tabs = 0
        self.campos[idx] = {"dato": nombre, "tabuladores": max(0, tabs)}
        self.refresh_listbox()
        self.select_index(idx)

    def move_up(self):
        idx = self.current_index()
        if idx is None or idx == 0: return
        self.campos[idx-1], self.campos[idx] = self.campos[idx], self.campos[idx-1]
        self.refresh_listbox()
        self.select_index(idx-1)

    def move_down(self):
        idx = self.current_index()
        if idx is None or idx >= len(self.campos)-1: return
        self.campos[idx+1], self.campos[idx] = self.campos[idx], self.campos[idx+1]
        self.refresh_listbox()
        self.select_index(idx+1)

    def dup_field(self):
        idx = self.current_index()
        if idx is None: return
        item = dict(self.campos[idx])
        item["dato"] += " (copia)"
        self.campos.insert(idx+1, item)
        self.refresh_listbox()
        self.select_index(idx+1)

    def delete_field(self):
        idx = self.current_index()
        if idx is None: return
        if len(self.campos) <= 1:
            messagebox.showinfo("Campos", "Debe existir al menos un campo.")
            return
        del self.campos[idx]
        self.refresh_listbox()
        self.select_index(min(idx, len(self.campos)-1))

    # Carga de existente para editar
    def _cargar_existente(self, nombre_base):
        path = os.path.join(CONFIG_DIR, nombre_base + ".json")
        if not os.path.exists(path):
            messagebox.showerror("Error", f"No se encontró '{nombre_base}.json'.")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo leer la configuración:\n{e}")
            return

        self.entry_nombre.delete(0, tk.END)
        self.entry_nombre.insert(0, data.get("nombre", nombre_base))
        self.nombre_original = nombre_base

        loaded = data.get("campos", [])
        self.campos = []
        for c in loaded:
            try:
                dato = (c.get("dato", "") or "").strip() or "Sin nombre"
                tabs = int(c.get("tabuladores", 0))
            except Exception:
                dato, tabs = "Sin nombre", 0
            self.campos.append({"dato": dato, "tabuladores": max(0, tabs)})

        if not self.campos:
            self.campos = [dict(x) for x in DEFAULT_FIELDS]

        self.refresh_listbox()
        self.select_index(0)

    # Guardado (crear o editar)
    def guardar_config(self):
        nombre = self.entry_nombre.get().strip().replace(" ", "_")
        if not nombre:
            messagebox.showerror("Error", "El nombre no puede estar vacío.")
            return

        os.makedirs(CONFIG_DIR, exist_ok=True)
        filename = nombre + ".json"
        path = os.path.join(CONFIG_DIR, filename)

        payload = {"nombre": nombre, "campos": []}
        for c in self.campos:
            try:
                dato = (c["dato"] or "").strip() or "Sin nombre"
                tabs = int(c["tabuladores"])
            except Exception:
                dato, tabs = "Sin nombre", 0
            payload["campos"].append({"dato": dato, "tabuladores": max(0, tabs)})

        if self.modo == "crear":
            if os.path.exists(path):
                messagebox.showerror("Error", f"Ya existe una configuración llamada '{filename}'.")
                return
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo guardar:\n{e}")
                return
            messagebox.showinfo("Guardado", f"Configuración '{filename}' creada.")
            self.destroy()
        else:
            # Editar: permitir renombrar
            if self.nombre_original and self.nombre_original != nombre:
                new_path = path
                old_path = os.path.join(CONFIG_DIR, self.nombre_original + ".json")
                if os.path.exists(new_path):
                    messagebox.showerror("Error", f"Ya existe una configuración llamada '{filename}'.")
                    return
                try:
                    with open(new_path, "w", encoding="utf-8") as f:
                        json.dump(payload, f, indent=2, ensure_ascii=False)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo renombrar:\n{e}")
                    return
                self.nombre_original = nombre
            else:
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(payload, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo guardar:\n{e}")
                    return
            messagebox.showinfo("Guardado", f"Se guardaron los cambios en '{filename}'.")
            self.destroy()


# -----------------------------
# Ventana 1 (selector)
# -----------------------------
class SelectorInicial(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DMS - Configuraciones")
        self.geometry("560x260")
        self.configure(bg=COLOR_BG)
        self._apply_icon()

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=COLOR_BG)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=("Segoe UI", 12))
        style.configure("TButton", font=("Segoe UI", 11), padding=8, background=COLOR_ACCENT, foreground="white")
        style.map("TButton", background=[('active', '#d32f2f')])
        style.configure("Danger.TButton", background="#c62828", foreground="white")
        style.map("Danger.TButton", background=[('active', '#b71c1c')])
        style.configure("TCombobox", fieldbackground="white", background="white", foreground="black")

        wrap = ttk.Frame(self, padding=20, style="TFrame")
        wrap.pack(fill="both", expand=True)

        self._logo_ref = None
        try:
            if Image and ImageTk:
                for p in ICON_CANDIDATES:
                    if os.path.exists(p):
                        img = Image.open(p).resize((54, 54))
                        self._logo_ref = ImageTk.PhotoImage(img)
                        ttk.Label(wrap, image=self._logo_ref, background=COLOR_BG).pack(pady=(0, 8))
                        break
        except Exception:
            pass

        ttk.Label(wrap, text="Seleccionar configuración:", style="TLabel").pack(anchor="w", pady=(0,6))
        self.cb_var = StringVar()
        self.cb = ttk.Combobox(wrap, textvariable=self.cb_var, state="readonly", width=45)
        self.cb.pack(fill="x")
        self.cargar_lista_configs()
        self.cb_var.set("(Crear nueva)")

        btns = ttk.Frame(wrap, style="TFrame")
        btns.pack(pady=18)
        ttk.Button(btns, text="Crear nueva", command=self.abrir_creacion).pack(side="left", padx=(0,10))
        ttk.Button(btns, text="Editar seleccionada", command=self.abrir_edicion).pack(side="left", padx=(0,10))
        ttk.Button(btns, text="Eliminar seleccionada", style="Danger.TButton", command=self.eliminar_seleccion).pack(side="left")

    def _apply_icon(self):
        for p in ICON_CANDIDATES:
            try:
                if os.path.exists(p):
                    self.iconbitmap(default=p); return
            except Exception:
                pass

    def cargar_lista_configs(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        archivos = [f[:-5] for f in os.listdir(CONFIG_DIR) if f.lower().endswith(".json")]
        archivos.sort(key=str.lower)
        self.cb["values"] = ["(Crear nueva)"] + archivos

    def abrir_creacion(self):
        editor = EditorConfig(self, modo="crear")
        self.wait_window(editor)
        self.cargar_lista_configs()

    def abrir_edicion(self):
        val = self.cb_var.get().strip()
        if val in ("", "(Crear nueva)"):
            messagebox.showinfo("Editar", "Selecciona una configuración existente para editar.")
            return
        editor = EditorConfig(self, modo="editar", nombre_existente=val)
        self.wait_window(editor)
        self.cargar_lista_configs()
        self.cb_var.set(val)

    def eliminar_seleccion(self):
        val = self.cb_var.get().strip()
        if val in ("", "(Crear nueva)"):
            messagebox.showinfo("Eliminar", "Selecciona una configuración existente.")
            return
        path = os.path.join(CONFIG_DIR, val + ".json")
        if not os.path.exists(path):
            messagebox.showerror("Eliminar", f"No se encontró '{val}.json'.")
            self.cargar_lista_configs()
            return
        if messagebox.askyesno("Confirmar", f"¿Eliminar la configuración '{val}.json'?"):
            try:
                os.remove(path)
                messagebox.showinfo("Eliminar", f"Se eliminó '{val}.json'.")
            except Exception as e:
                messagebox.showerror("Eliminar", f"No se pudo eliminar:\n{e}")
                return
            self.cargar_lista_configs()
            self.cb_var.set("(Crear nueva)")

if __name__ == "__main__":
    SelectorInicial().mainloop()
