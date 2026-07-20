import importlib.util, json, os, shutil, sys, tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk


def _load_runtime_module(module_name, filename):
    root = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(root, "assets", "runtime", filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar el módulo interno: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


legacy = _load_runtime_module("dms_editor_core", "editor_core.py")

HOTKEY="Ctrl+Alt+C"
ROOT=os.path.dirname(sys.executable) if getattr(sys,"frozen",False) else os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
CFG=os.path.join(ROOT,"configs"); FORMS=os.path.join(CFG,"formularios"); SYSTEM=os.path.join(CFG,"sistema"); FORMATS=os.path.join(CFG,"formatos")
ACTIVE=os.path.join(SYSTEM,"config_actual.json"); FAVORITES=os.path.join(SYSTEM,"favoritos.json")
BG="#212121"; PANEL="#2a2a2a"; RED="#e53935"


def read(path,default):
    try:
        with open(path,"r",encoding="utf-8") as f:return json.load(f)
    except Exception:return default


def write(path,data):
    os.makedirs(os.path.dirname(path),exist_ok=True); tmp=path+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:json.dump(data,f,indent=2,ensure_ascii=False)
    os.replace(tmp,path)


def move_old(src,folder):
    if not os.path.isfile(src):return
    os.makedirs(folder,exist_ok=True); dst=os.path.join(folder,os.path.basename(src))
    if os.path.exists(dst):
        try:
            if open(src,"rb").read()==open(dst,"rb").read():os.remove(src);return
        except Exception:pass
        stem,ext=os.path.splitext(os.path.basename(dst)); dst=os.path.join(folder,f"{stem}_migrada_{datetime.now():%Y%m%d_%H%M%S}{ext}")
    shutil.move(src,dst)


def migrate():
    for d in (FORMS,SYSTEM,FORMATS):os.makedirs(d,exist_ok=True)
    for name,folder in (("config_actual.json",SYSTEM),("ultimo_com.json",SYSTEM),("favoritos.json",SYSTEM),("formatos_cedulas.json",FORMATS)):
        move_old(os.path.join(CFG,name),folder)
    for name in os.listdir(CFG):
        path=os.path.join(CFG,name)
        if os.path.isfile(path) and name.lower().endswith(".json"):move_old(path,FORMS)


def configs():
    os.makedirs(FORMS,exist_ok=True)
    return sorted((n for n in os.listdir(FORMS) if n.lower().endswith(".json")),key=str.lower)


def raw_active():return os.path.basename(str(read(ACTIVE,{}).get("activa","")))
def set_active(name):
    if name not in configs():raise ValueError("La configuración no existe.")
    write(ACTIVE,{"activa":name})


def favorites():
    d=read(FAVORITES,{}); available=set(configs())
    a=os.path.basename(str(d.get("favorito_1",""))); b=os.path.basename(str(d.get("favorito_2","")))
    return (a if a in available else "",b if b in available else "")


def save_favorites(a,b):
    if a not in configs() or b not in configs():raise ValueError("Seleccione dos configuraciones existentes.")
    if a==b:raise ValueError("Las favoritas deben ser diferentes.")
    write(FAVORITES,{"favorito_1":a,"favorito_2":b,"atajo":HOTKEY})


def replace_refs(old,new=""):
    d=read(FAVORITES,{}); a=os.path.basename(str(d.get("favorito_1",""))); b=os.path.basename(str(d.get("favorito_2","")))
    changed=False
    if a==old:a=new;changed=True
    if b==old:b=new;changed=True
    if changed:write(FAVORITES,{"favorito_1":a,"favorito_2":b,"atajo":HOTKEY})
    if raw_active()==old:
        if new:set_active(new)
        else:
            remain=[x for x in configs() if x!=old]
            if remain:set_active(remain[0])
            elif os.path.exists(ACTIVE):os.remove(ACTIVE)


def patch_legacy():
    legacy.CONFIG_DIR=FORMS
    # Las rutas de icono del editor original siguen siendo válidas dentro del instalador.


class Manager(tk.Tk):
    def __init__(self):
        super().__init__(); migrate(); patch_legacy()
        self.title("DMS - Configuraciones"); self.geometry("760x450"); self.minsize(700,420); self.configure(bg=BG)
        try:
            for p in legacy.ICON_CANDIDATES:
                if os.path.exists(p):self.iconbitmap(default=p);break
        except Exception:pass
        s=ttk.Style(self);s.theme_use("clam");s.configure("A.TFrame",background=BG);s.configure("P.TFrame",background=PANEL)
        s.configure("H.TLabel",background=BG,foreground="white",font=("Segoe UI",18,"bold"));s.configure("A.TLabel",background=BG,foreground="white",font=("Segoe UI",10))
        s.configure("P.TLabel",background=PANEL,foreground="white",font=("Segoe UI",10));s.configure("R.TButton",background=RED,foreground="white",font=("Segoe UI",10,"bold"),padding=8)
        s.configure("G.TButton",background="#3a3a3a",foreground="white",font=("Segoe UI",10),padding=8);s.configure("D.TButton",background="#b71c1c",foreground="white",font=("Segoe UI",10),padding=8)
        self.build();self.refresh()

    def build(self):
        root=ttk.Frame(self,style="A.TFrame",padding=18);root.pack(fill="both",expand=True)
        ttk.Label(root,text="Configuraciones de formularios",style="H.TLabel").pack(anchor="w")
        ttk.Label(root,text="El selector solo muestra archivos de configs/formularios.",style="A.TLabel").pack(anchor="w",pady=(2,14))
        card=ttk.Frame(root,style="P.TFrame",padding=14);card.pack(fill="x")
        ttk.Label(card,text="Configuración:",style="P.TLabel").grid(row=0,column=0,sticky="w")
        self.selected=tk.StringVar();self.combo=ttk.Combobox(card,textvariable=self.selected,state="readonly",width=54);self.combo.grid(row=1,column=0,sticky="ew",pady=(5,10));card.grid_columnconfigure(0,weight=1)
        buttons=ttk.Frame(card,style="P.TFrame");buttons.grid(row=2,column=0,sticky="ew")
        ttk.Button(buttons,text="Crear nueva",style="R.TButton",command=self.create).pack(side="left")
        ttk.Button(buttons,text="Editar",style="G.TButton",command=self.edit).pack(side="left",padx=7)
        ttk.Button(buttons,text="Activar",style="G.TButton",command=self.activate).pack(side="left")
        ttk.Button(buttons,text="Eliminar",style="D.TButton",command=self.delete).pack(side="right")
        fav=ttk.Frame(root,style="P.TFrame",padding=14);fav.pack(fill="x",pady=(14,0))
        ttk.Label(fav,text=f"Favoritas para cambio rápido — atajo global {HOTKEY}",style="P.TLabel").grid(row=0,column=0,columnspan=3,sticky="w",pady=(0,10))
        self.f1=tk.StringVar();self.f2=tk.StringVar()
        ttk.Label(fav,text="Favorita 1",style="P.TLabel").grid(row=1,column=0,sticky="w");ttk.Label(fav,text="Favorita 2",style="P.TLabel").grid(row=1,column=1,sticky="w",padx=(12,0))
        self.c1=ttk.Combobox(fav,textvariable=self.f1,state="readonly",width=29);self.c2=ttk.Combobox(fav,textvariable=self.f2,state="readonly",width=29)
        self.c1.grid(row=2,column=0,sticky="ew",pady=(4,0));self.c2.grid(row=2,column=1,sticky="ew",padx=(12,0),pady=(4,0))
        ttk.Button(fav,text="Guardar favoritas",style="R.TButton",command=self.save_favs).grid(row=2,column=2,padx=(12,0));fav.grid_columnconfigure(0,weight=1);fav.grid_columnconfigure(1,weight=1)
        self.status=tk.StringVar();ttk.Label(root,textvariable=self.status,style="A.TLabel").pack(anchor="w",pady=(14,0))

    def refresh(self,preferred=""):
        values=configs();self.combo["values"]=values;self.c1["values"]=values;self.c2["values"]=values
        current=preferred if preferred in values else self.selected.get()
        if current not in values:current=raw_active() if raw_active() in values else (values[0] if values else "")
        self.selected.set(current);a,b=favorites();self.f1.set(a);self.f2.set(b)
        self.status.set(f"Activa: {raw_active() or 'ninguna'} | Favoritas: {a or 'sin definir'} ↔ {b or 'sin definir'}")

    def create(self):
        before=set(configs());win=legacy.EditorConfig(self,modo="crear");self.wait_window(win);added=list(set(configs())-before);self.refresh(added[0] if len(added)==1 else "")
    def edit(self):
        old=self.selected.get()
        if not old:return
        before=set(configs());win=legacy.EditorConfig(self,modo="editar",nombre_existente=old[:-5] if old.lower().endswith(".json") else old);self.wait_window(win)
        after=set(configs());new=list(after-before)
        if old not in after and len(new)==1:replace_refs(old,new[0]);self.refresh(new[0])
        else:self.refresh(old)
    def activate(self):
        try:set_active(self.selected.get());self.refresh(self.selected.get());messagebox.showinfo("Activa",f"Configuración activa:\n{self.selected.get()}",parent=self)
        except Exception as e:messagebox.showerror("Error",str(e),parent=self)
    def delete(self):
        name=self.selected.get()
        if not name or not messagebox.askyesno("Confirmar",f"¿Eliminar '{name}'?",parent=self):return
        try:
            os.remove(os.path.join(FORMS,name));replace_refs(name);self.refresh()
        except Exception as e:messagebox.showerror("Error",str(e),parent=self)
    def save_favs(self):
        try:save_favorites(self.f1.get(),self.f2.get());self.refresh(self.selected.get());messagebox.showinfo("Favoritas",f"Use {HOTKEY} para alternar entre ambas.",parent=self)
        except Exception as e:messagebox.showerror("Favoritas",str(e),parent=self)

if __name__=="__main__":Manager().mainloop()
