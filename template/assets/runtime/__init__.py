# Módulos internos incluidos por PyInstaller.
# La importación instala el supervisor seguro para cambio de usuario en consola.
from assets.runtime import dms_console_session_guard as _console_session_guard

__all__ = ["_console_session_guard"]
