"""Exploración GATT del mdoc únicamente para comprobar las características.

No lee valores, no escribe ni se suscribe a notificaciones. No solicita datos
de la IDC ni autentica identidad. UUID de servicio tomado del QR con consentimiento.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from .ble_link_probe import _get_transport_options, _load_cbor
from .ble_runtime import classify_ble_import_error
from .gatt_codec import (
    CLIENT_TO_SERVER_UUID,
    SERVER_TO_CLIENT_UUID,
    STATE_UUID,
)


async def _discover_gatt(service_uuid: UUID, scan_seconds: float) -> dict[str, bool]:
    """Encuentra SOLO el servicio del QR y descubre propiedades sin leer valores."""
    from bleak import BleakClient, BleakScanner

    found = asyncio.Event()
    matching_devices: list[Any] = []
    target = str(service_uuid).casefold()

    def on_advertisement(device: Any, advertisement: Any) -> None:
        uuids = getattr(advertisement, "service_uuids", ()) or ()
        if not matching_devices and any(str(value).casefold() == target for value in uuids):
            matching_devices.append(device)
            found.set()

    async with BleakScanner(
        detection_callback=on_advertisement,
        service_uuids=[str(service_uuid)],
        scanning_mode="active",
    ):
        try:
            await asyncio.wait_for(found.wait(), timeout=scan_seconds)
        except TimeoutError:
            return {"device_found": False}

    async with BleakClient(matching_devices[0], timeout=10.0) as client:
        if not client.is_connected:
            return {"device_found": True, "ble_connected": False}
        service = client.services.get_service(str(service_uuid))
        if service is None:
            return {
                "device_found": True, "ble_connected": True,
                "gatt_service_found": False,
            }
        characteristics: dict[str, set[str]] = {}
        # Se inspeccionan SOLO las características del servicio del QR;
        # se ignoran otros servicios y NO se devuelve ningún UUID.
        for char in service.characteristics:
            uuid = str(char.uuid).casefold()
            if uuid in (
                STATE_UUID, CLIENT_TO_SERVER_UUID, SERVER_TO_CLIENT_UUID,
            ):
                characteristics[uuid] = {
                    str(prop).casefold() for prop in (char.properties or [])
                }
        state = characteristics.get(STATE_UUID)
        c2s = characteristics.get(CLIENT_TO_SERVER_UUID)
        s2c = characteristics.get(SERVER_TO_CLIENT_UUID)
        return {
            "device_found": True,
            "ble_connected": True,
            "gatt_service_found": True,
            "state_characteristic_found": state is not None,
            "client_to_server_characteristic_found": c2s is not None,
            "server_to_client_characteristic_found": s2c is not None,
            "state_supports_notify": state is not None and "notify" in state,
            "state_supports_write": state is not None and (
                "write" in state or "write-without-response" in state
            ),
            "client_to_server_supports_write": c2s is not None and (
                "write-without-response" in c2s or "write" in c2s
            ),
            "server_to_client_supports_notify": s2c is not None and "notify" in s2c,
        }


def probe_mdoc_ble_gatt(
    raw_qr: bytes,
    *,
    consent: bool,
    timeout_seconds: float = 30.0,
    decode_cbor: Callable[[bytes], Any] | None = None,
    discover: Callable[[UUID, float], Awaitable[dict[str, bool]]] | None = None,
) -> dict[str, object]:
    """Reporte categórico de GATT. Sin datos personales ni identificadores."""
    report: dict[str, object] = {
        "schema_version": 1,
        "purpose": "consented_read_only_gatt_metadata_check_only",
        "nearby_scan_scope": "qr_service_uuid_only",
        "holder_peripheral_announced": False,
        "ble_service_uuid_present": False,
        "ble_link_established": False,
        "gatt_service_found": False,
        "gatt_characteristics_inspected": False,
        "gatt_link_tested": False,
        "state_characteristic_found": False,
        "client_to_server_characteristic_found": False,
        "server_to_client_characteristic_found": False,
        "state_supports_notify": False,
        "state_supports_write": False,
        "client_to_server_supports_write": False,
        "server_to_client_supports_notify": False,
        "gatt_profile_properties_match": False,
        "gatt_values_read": False,
        "gatt_writes_performed": False,
        "gatt_notifications_subscribed": False,
        "mdoc_session_established": False,
        "issuer_signature_verified": False,
        "verified_identity": False,
        "idc_verification_available": False,
        "status": "consent_required",
    }
    if not consent:
        return report
    if not 3 <= timeout_seconds <= 30:
        report["status"] = "invalid_timeout"
        return report

    try:
        state, peripheral, _central, service_uuid = _get_transport_options(
            raw_qr, decode_cbor=decode_cbor or _load_cbor
        )
    except ImportError:
        report["status"] = "cbor2_not_installed"
        return report
    except Exception:
        report["status"] = "invalid_cbor"
        return report

    report["holder_peripheral_announced"] = peripheral
    report["ble_service_uuid_present"] = service_uuid is not None
    if service_uuid is None:
        report["status"] = state
        return report

    try:
        result = asyncio.run(
            asyncio.wait_for(
                (discover or _discover_gatt)(service_uuid, timeout_seconds),
                timeout=timeout_seconds + 15.0,
            )
        )
    except ImportError as exc:
        report["status"] = classify_ble_import_error(exc)
        return report
    except TimeoutError:
        report["status"] = "gatt_discovery_timeout"
        return report
    except Exception:
        report["status"] = "gatt_discovery_error"
        return report

    if not isinstance(result, dict) or not result or any(
        type(value) is not bool for value in result.values()
    ):
        report["status"] = "gatt_discovery_error"
        return report

    if not result.get("device_found"):
        report["status"] = "service_not_found"
        return report
    if not result.get("ble_connected"):
        report["status"] = "connection_not_established"
        return report
    report["ble_link_established"] = True
    if not result.get("gatt_service_found"):
        report["status"] = "gatt_service_missing_after_connection"
        return report

    report["gatt_service_found"] = True
    report["gatt_characteristics_inspected"] = True
    report["gatt_link_tested"] = True

    fields = (
        "state_characteristic_found",
        "client_to_server_characteristic_found",
        "server_to_client_characteristic_found",
        "state_supports_notify",
        "state_supports_write",
        "client_to_server_supports_write",
        "server_to_client_supports_notify",
    )
    for field in fields:
        report[field] = result.get(field) is True

    required = (
        "state_supports_notify",
        "state_supports_write",
        "client_to_server_supports_write",
        "server_to_client_supports_notify",
    )
    profile_matches = all(report[key] for key in required)
    report["gatt_profile_properties_match"] = profile_matches
    report["status"] = (
        "gatt_profile_discovered_not_session_started"
        if profile_matches else "gatt_profile_incomplete_or_different"
    )
    return report
