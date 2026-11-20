"""Diagnóstico opcional del adaptador BLE mediante API oficial Windows Runtime.

No escanea dispositivos cercanos, no establece conexiones, no analiza datos de
personas ni verifica credenciales IDC. La dependencia WinRT es opcional.
"""
from __future__ import annotations

import asyncio
import platform
from collections.abc import Awaitable, Callable
from typing import Any


async def _read_windows_adapter() -> dict[str, bool] | None:
    # Import diferido: 'py -m tools.idc_diagnostic --bluetooth-check'
    # debe seguir funcionando sin WinRT ni otros paquetes externos.
    from winrt.windows.devices.bluetooth import BluetoothAdapter

    adapter = await BluetoothAdapter.get_default_async()
    if adapter is None:
        return None
    return {
        "low_energy_supported": adapter.is_low_energy_supported,
        "central_role_supported": adapter.is_central_role_supported,
        "peripheral_role_supported": adapter.is_peripheral_role_supported,
    }


def probe_ble_capabilities(
    *,
    system_name: str | None = None,
    adapter_reader: Callable[[], Awaitable[dict[str, bool] | None]] | None = None,
) -> dict[str, Any]:
    """Consulta roles BLE sin ejecutar descubrimiento ni acceder a una IDC.

    Las propiedades indican capacidades del adaptador, no que el protocolo de
    la IDC, el SDK oficial ni la verificación criptográfica funcionen.
    """
    current_system = system_name or platform.system()
    report: dict[str, Any] = {
        "schema_version": 1,
        "purpose": "ble_capability_diagnostic_only",
        "operating_system": "Windows" if current_system == "Windows" else "other",
        "adapter_status": "unknown",
        "low_energy_supported": None,
        "central_role_supported": None,
        "peripheral_role_supported": None,
        "nearby_device_scan_performed": False,
        "gatt_connection_tested": False,
        "idc_session_verified": False,
        "verified_identity": False,
        "idc_verification_available": False,
    }
    if current_system != "Windows":
        report["adapter_status"] = "not_applicable"
        return report

    read = adapter_reader or _read_windows_adapter
    try:
        properties = asyncio.run(asyncio.wait_for(read(), timeout=8.0))
    except (ImportError, ModuleNotFoundError):
        report["adapter_status"] = "winrt_dependency_missing"
        return report
    except (Exception, asyncio.CancelledError):
        # No registrar excepciones WinRT: pueden incluir identificadores locales.
        report["adapter_status"] = "api_error"
        return report

    if properties is None:
        report["adapter_status"] = "no_default_adapter"
        return report

    required = (
        "low_energy_supported",
        "central_role_supported",
        "peripheral_role_supported",
    )
    if not isinstance(properties, dict) or any(type(properties.get(k)) is not bool for k in required):
        report["adapter_status"] = "api_error"
        return report

    report["adapter_status"] = "detected"
    for name in required:
        report[name] = properties[name]
    return report


__all__ = ["probe_ble_capabilities"]
