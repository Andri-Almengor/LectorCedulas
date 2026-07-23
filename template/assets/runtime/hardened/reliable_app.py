from __future__ import annotations

from .desktop_app import DesktopApplication
from .reliable_writer import ReliableFormWriter
from .windows_control import WindowsControlProbe


class ReliableDesktopApplication(DesktopApplication):
    """Aplicación de escritorio con escritor x64 robusto y errores visibles."""

    def __init__(self, root_dir=None):
        super().__init__(root_dir=root_dir)
        self.writer = ReliableFormWriter(
            windows=self.windows,
            control_probe=WindowsControlProbe(self.windows),
            logger=self._log,
        )
        self.queue.writer = self.writer

    def _log(self, message: str) -> None:
        text = str(message or "")
        if text.startswith("queue_failed:"):
            parts = text.split(":", 2)
            reason = parts[2] if len(parts) > 2 else "escritura_fallida"
            if hasattr(self, "last_error"):
                self.last_error = f"Escritura fallida: {reason}"
        elif text.startswith("queue_exception:"):
            parts = text.split(":", 2)
            reason = parts[2] if len(parts) > 2 else "error_desconocido"
            if hasattr(self, "last_error"):
                self.last_error = f"Error de escritura: {reason}"
        elif text.startswith("input_delivery_error:"):
            if hasattr(self, "last_error"):
                self.last_error = text.replace("input_delivery_error:", "Entrada: ")
        super()._log(text)
