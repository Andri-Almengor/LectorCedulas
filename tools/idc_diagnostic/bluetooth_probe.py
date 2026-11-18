"""Comprobación no invasiva del estado Bluetooth en Windows.

No sondea dispositivos cercanos, no conecta con celulares ni verifica una IDC.
El estado de la clase Bluetooth NO confirma soporte BLE/GATT.
"""
from __future__ import annotations

import platform
import subprocess
from typing import Any, Callable


_PS_CLASS_CHECK = (
    "$ErrorActionPreference = 'Stop'; "
    "$devices = @(Get-PnpDevice -Class Bluetooth -ErrorAction Stop | "
    "Where-Object { $_.Status -eq 'OK' }); "
    "if ($devices.Count -gt 0) { 'PRESENT' } else { 'ABSENT' }"
)


def probe_bluetooth(
    *,
    system_name: str | None = None,
    runner: Callable[..., Any] | None = None,
) -> dict[str, object]:
    """Produce un informe sanitizado, no una afirmación de compatibilidad IDC.

    `PRESENT` confirma únicamente que Windows enumera elementos activos en
    la clase Bluetooth. El radio BLE, los roles GATT y el SDK siguen sin probar.
    """
    report: dict[str, object] = {
        "schema_version": 1,
        "purpose": "hardware_diagnostic_only",
        "operating_system": "Windows" if (system_name or platform.system()) == "Windows" else "other",
        "bluetooth_class_status": "unknown",
        "ble_session_supported": "not_tested",
        "idc_verification_available": False,
        "no_bluetooth_fallback": "official_verifier_and_manual_registration",
    }
    if report["operating_system"] != "Windows":
        report["bluetooth_class_status"] = "not_applicable"
        return report

    run = runner or subprocess.run
    try:
        completed = run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _PS_CLASS_CHECK],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return report

    # Nunca incluye nombres de dispositivos, MAC, drivers ni stdout sin procesar.
    if completed.returncode == 0:
        value = completed.stdout.strip()
        if value == "PRESENT":
            report["bluetooth_class_status"] = "detected"
        elif value == "ABSENT":
            report["bluetooth_class_status"] = "not_detected"
    return report


__all__ = ["probe_bluetooth"]
