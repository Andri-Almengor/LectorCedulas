"""Herramientas de emisión, build y actualización del producto.

El generador histórico de Inno Setup usa una plantilla multilínea con rutas de
Windows. Python puede interpretar secuencias como ``\a`` y ``\f`` dentro de esa
plantilla antes de escribir el archivo ``.iss``. Este paquete instala una guarda
centralizada para que todos los consumidores (dashboard, pruebas y builds)
reciban siempre un script válido, sin caracteres de control ocultos.
"""

from __future__ import annotations

from importlib import import_module


def _install_release_builder_guard():
    module = import_module(".release_builder", __name__)
    original = module._write_inno
    if getattr(original, "_dms_inno_guard", False):
        return module

    def guarded_write_inno(*args, **kwargs):
        script = original(*args, **kwargs)
        text = script.read_text(encoding="utf-8")

        # Recupera las letras consumidas por escapes de Python dentro de rutas
        # Windows: \assets -> BEL + "ssets" y \formatos -> FF + "ormatos".
        replacements = {
            "\a": "\\a",
            "\b": "\\b",
            "\f": "\\f",
            "\t": "\\t",
            "\v": "\\v",
        }
        for control, literal in replacements.items():
            text = text.replace(control, literal)

        forbidden = sorted(
            {ord(char) for char in text if ord(char) < 32 and char not in "\r\n"}
        )
        if forbidden:
            raise module.BuildError(
                "El script Inno contiene caracteres de control no permitidos: "
                + ", ".join(str(code) for code in forbidden)
            )

        script.write_text(text, encoding="utf-8")
        return script

    guarded_write_inno._dms_inno_guard = True
    module._write_inno = guarded_write_inno
    return module


# Se importa y protege de forma anticipada porque varios consumidores usan
# ``from tools.release_builder import ...`` y necesitan la guarda antes de
# obtener las funciones del submódulo.
release_builder = _install_release_builder_guard()

__all__ = ["release_builder"]
