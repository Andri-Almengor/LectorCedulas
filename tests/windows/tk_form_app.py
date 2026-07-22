import json
import tkinter as tk
from pathlib import Path

RESULT = Path(__file__).with_name("tk_form_result.json")
root = tk.Tk()
root.title("DMS QA Tkinter Form")
entries = []
for label in ("Primer Apellido", "Nombre", "Cedula", "Fecha de Nacimiento"):
    row = tk.Frame(root)
    row.pack(fill="x", padx=12, pady=5)
    tk.Label(row, text=label, width=22, anchor="w").pack(side="left")
    entry = tk.Entry(row, name=label.lower().replace(" ", "_"))
    entry.pack(side="left", fill="x", expand=True)
    entries.append((label, entry))


def save():
    RESULT.write_text(json.dumps({label: entry.get() for label, entry in entries}, ensure_ascii=False), encoding="utf-8")
    root.destroy()


tk.Button(root, text="Guardar resultado", command=save).pack(pady=10)
entries[0][1].focus_set()
root.mainloop()
