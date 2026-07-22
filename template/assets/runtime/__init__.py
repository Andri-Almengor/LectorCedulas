# Módulos internos incluidos por PyInstaller.
# Las importaciones instalan protecciones de sesión y escritura secuencial.
from assets.runtime import dms_console_session_guard as _console_session_guard
from assets.runtime import dms_scan_queue_guard as _scan_queue_guard

__all__ = ["_console_session_guard", "_scan_queue_guard"]
