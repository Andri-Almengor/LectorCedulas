"""Diagnóstico BLE agregado de bajo impacto para servicio mDoc de un QR autorizado.

La búsqueda temporal SIN filtro observa publicidad BLE cercana, por eso exige
consentimiento y opt-in adicional. No guarda nombres, MAC, UUID ni paquetes
de terceros, no se conecta a ellos y devuelve únicamente indicadores bool.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from .ble_link_probe import _get_transport_options, _load_cbor

_DEFAULT_SECONDS = 20.0


async def _observe_advertisements(service_uuid: UUID, seconds: float) -> dict[str, bool]:
    from bleak import BleakScanner

    target = str(service_uuid).casefold()
    seen = {
        "any_ble_advertisements_seen": False,
        "qr_service_uuid_advertised": False,
        "qr_uuid_in_service_data": False,
    }

    def on_advertisement(_device: Any, advertising: Any) -> None:
        # Procesar sin conservar dispositivos ni identificadores.
        seen["any_ble_advertisements_seen"] = True
        service_uuids = getattr(advertising, "service_uuids", ()) or ()
        if any(str(uid).casefold() == target for uid in service_uuids):
            seen["qr_service_uuid_advertised"] = True
        service_data = getattr(advertising, "service_data", {}) or {}
        if isinstance(service_data, dict) and any(
            str(uid).casefold() == target for uid in service_data
        ):
            seen["qr_uuid_in_service_data"] = True

    # SIN filtro de UUID, para diferenciar problema de publicidad del teléfono
    # frente a un escáner Bluetooth que no recibe anuncios en absoluto.
    # No se conectan dispositivos; event args se descartan inmediatamente.
    async with BleakScanner(detection_callback=on_advertisement, scanning_mode="active"):
        await asyncio.sleep(seconds)
    return seen


def observe_mdoc_ble_advertising(
    raw_qr: bytes,
    *,
    consent: bool,
    nearby_scan_ok: bool,
    duration_seconds: float = _DEFAULT_SECONDS,
    decode_cbor: Callable[[bytes], Any] | None = None,
    observe: Callable[[UUID, float], Awaitable[dict[str, bool]]] | None = None,
) -> dict[str, object]:
    """Observación sin conexión ni verificación. Reporte apto para compartir."""
    report: dict[str, object] = {
        "schema_version": 1,
        "purpose": "temporary_ble_advertisement_diagnostic_only",
        "nearby_scan_scope": "temporary_all_advertisements_no_identifiers_retained",
        "any_ble_advertisements_seen": False,
        "qr_service_uuid_advertised": False,
        "qr_uuid_in_service_data": False,
        "holder_peripheral_announced": False,
        "ble_service_uuid_present": False,
        "ble_link_established": False,
        "gatt_link_tested": False,
        "mdoc_session_established": False,
        "issuer_signature_verified": False,
        "verified_identity": False,
        "idc_verification_available": False,
        "status": "consent_required",
    }
    if not consent or not nearby_scan_ok:
        return report
    if not 3 <= duration_seconds <= 30:
        report["status"] = "invalid_scan_duration"
        return report

    try:
        state, peripheral, _central, target_uuid = _get_transport_options(
            raw_qr, decode_cbor=decode_cbor or _load_cbor,
        )
    except (ImportError, ModuleNotFoundError):
        report["status"] = "cbor2_not_installed"
        return report
    except Exception:
        report["status"] = "invalid_or_unsupported_engagement"
        return report

    report["holder_peripheral_announced"] = peripheral
    report["ble_service_uuid_present"] = target_uuid is not None
    if target_uuid is None:
        report["status"] = state
        return report

    try:
        result = asyncio.run(
            asyncio.wait_for(
                (observe or _observe_advertisements)(target_uuid, duration_seconds),
                timeout=duration_seconds + 5.0,
            )
        )
    except (ImportError, ModuleNotFoundError):
        report["status"] = "bleak_not_installed"
        return report
    except TimeoutError:
        report["status"] = "scan_timeout"
        return report
    except Exception:
        report["status"] = "ble_scan_error"
        return report

    keys = (
        "any_ble_advertisements_seen",
        "qr_service_uuid_advertised",
        "qr_uuid_in_service_data",
    )
    if not isinstance(result, dict) or any(type(result.get(k)) is not bool for k in keys):
        report["status"] = "ble_scan_error"
        return report
    for name in keys:
        report[name] = result[name]

    if result["qr_service_uuid_advertised"]:
        report["status"] = "target_service_advertised"
    elif result["qr_uuid_in_service_data"]:
        report["status"] = "target_uuid_in_service_data_only"
    elif result["any_ble_advertisements_seen"]:
        report["status"] = "other_advertisements_seen_not_target"
    else:
        report["status"] = "no_ble_advertisements_received"
    return report
