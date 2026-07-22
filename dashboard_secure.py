"""Entrada segura del dashboard existente.

Conserva la interfaz y administración de clientes del dashboard actual, pero
reemplaza únicamente sus constructores de artefactos por el pipeline firmado y
reproducible. Las claves privadas se crean en LOCALAPPDATA y nunca se copian al
repositorio, instalador o paquete de actualización.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "template"))

import dashboard as dashboard_ui
from assets.runtime.hardened.version import VERSION
from tools.release_builder import make_installer_zip, make_update_zip


def main():
    dashboard_ui.APP_VERSION = VERSION
    dashboard_ui.make_installer_zip = make_installer_zip
    dashboard_ui.make_update_zip = make_update_zip
    app = dashboard_ui.Dashboard()
    app.mainloop()


if __name__ == "__main__":
    main()
