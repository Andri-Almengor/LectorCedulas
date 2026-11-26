"""Clasificación segura de fallos al cargar BLE/WinRT.

No desactiva políticas Windows, no importa Bluetooth durante la importación
del módulo y jamás devuelve rutas ni excepciones con identificadores.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def classify_ble_import_error(exc: ImportError) -> str:
    """Distingue una dependencia ausente del bloqueo de una extensión nativa."""
    if isinstance(exc, ModuleNotFoundError):
        return "ble_dependency_missing"
    message = str(exc).casefold()
    if any(phrase in message for phrase in (
        "application control",
        "control de aplicaciones",
        "app control",
        "smart app control",
        "applocker",
    )):
        return "windows_application_control_blocked"
    return "ble_native_extension_load_error"


def probe_ble_runtime(
    *, load: Callable[[], Any] | None = None,
) -> dict[str, object]:
    """Comprueba solo la carga de Bleak WinRT; no busca ni conecta dispositivos."""
    result: dict[str, object] = {
        "schema_version": 1,
        "purpose": "ble_runtime_import_check_only",
        "ble_runtime_imported": False,
        "bluetooth_scan_performed": False,
        "ble_link_established": False,
        "verified_identity": False,
        "idc_verification_available": False,
        "status": "not_started",
    }

    def load_windows_scanner() -> None:
        # Importar backend específico: importar 'BleakScanner' solo puede ser
        # exitoso aun cuando Windows prohíbe cargar winrt._winrt (.pyd).
        from bleak.backends.winrt.scanner import BleakScannerWinRT  # noqa: F401

    try:
        (load or load_windows_scanner)()
    except ImportError as exc:
        result["status"] = classify_ble_import_error(exc)
    except Exception:
        result["status"] = "ble_runtime_initialization_error"
    else:
        result["status"] = "ble_runtime_import_ok"
        result["ble_runtime_imported"] = True
    return result
