"""Prueba explícita y limitada de enlace BLE a un servicio anunciado en un QR mdoc.

NO descifra ni solicita atributos, NO verifica identidad y NO escribe formularios.
El QR se mantiene únicamente en memoria. Los UUID y nombres no se imprimen.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import RFC_4122, UUID

from .inspect import MAX_SCAN_BYTES
from .ble_runtime import classify_ble_import_error

_B64 = re.compile(rb"[A-Za-z0-9_-]+={0,2}\Z")
_SCAN_WINDOW_SECONDS = 18.0


def _report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "purpose": "consented_ble_transport_test_only",
        "verified_identity": False,
        "idc_verification_available": False,
        "mdoc_session_established": False,
        "ble_link_established": False,
        "gatt_link_tested": False,
        "nearby_scan_scope": "qr_service_uuid_only",
        "holder_peripheral_announced": False,
        "holder_central_announced": False,
        "ble_service_uuid_present": False,
        "link_status": "not_started",
    }


def _load_cbor(raw: bytes) -> Any:
    # Dependencia opcional. No es necesaria para los diagnósticos anteriores.
    import cbor2

    content = io.BytesIO(raw)
    decoder = cbor2.CBORDecoder(content)
    parsed = decoder.decode()
    if content.read(1):
        raise ValueError("extra_cbor_data")
    return parsed


def _get_transport_options(
    raw: bytes,
    *,
    decode_cbor: Callable[[bytes], Any],
) -> tuple[str, bool, bool, UUID | None]:
    if not isinstance(raw, bytes) or len(raw) > MAX_SCAN_BYTES:
        return "invalid_qr", False, False, None
    payload = raw.strip(b"\r\n\x00 \t")
    if not payload.lower().startswith(b"mdoc:"):
        return "invalid_qr", False, False, None
    encoded = payload[5:]
    if not encoded or not _B64.fullmatch(encoded):
        return "invalid_qr", False, False, None
    try:
        decoded = base64.b64decode(
            encoded + b"=" * (-len(encoded) % 4),
            altchars=b"-_",
            validate=True,
        )
        root = decode_cbor(decoded)
    except (binascii.Error, ValueError, TypeError, OverflowError, RecursionError):
        return "invalid_cbor", False, False, None
    if not isinstance(root, dict) or not isinstance(root.get(0), str) or not isinstance(root.get(2), list):
        return "unrecognized_engagement", False, False, None

    methods = [m for m in root[2] if isinstance(m, list) and len(m) == 3 and m[:2] == [2, 1]]
    if not methods:
        return "no_ble_method", False, False, None
    for method in methods:
        options = method[2]
        if not isinstance(options, dict):
            continue
        peripheral = options.get(0) is True  # teléfono actúa como servidor periférico
        central = options.get(1) is True
        key = options.get(10)
        if peripheral and isinstance(key, bytes) and len(key) == 16:
            candidate = UUID(bytes=key)
            if candidate.variant == RFC_4122:
                return "ready_for_targeted_scan", True, central, candidate
        if central and not peripheral:
            return "phone_central_mode_only", False, True, None
        if peripheral:
            return "missing_peripheral_uuid", True, central, None
    return "unsupported_ble_options", False, False, None


async def _connect_to_qr_service(service_uuid: UUID, timeout_seconds: float) -> tuple[bool, bool]:
    """Solo descubre el UUID específico, abre enlace brevemente y lo cierra."""
    from bleak import BleakClient, BleakScanner

    target = str(service_uuid).casefold()
    matched_device: list[Any] = []
    found = asyncio.Event()

    def on_advertisement(device: Any, advertisement: Any) -> None:
        announced = getattr(advertisement, "service_uuids", ()) or ()
        if not matched_device and any(str(value).casefold() == target for value in announced):
            matched_device.append(device)
            found.set()

    # La API del escáner recibe un filtro de UUID; nunca se publica información
    # de dispositivos ajenos ni se realiza descubrimiento indiscriminado.
    async with BleakScanner(
        detection_callback=on_advertisement,
        service_uuids=[str(service_uuid)],
        scanning_mode="active",
    ):
        try:
            await asyncio.wait_for(found.wait(), timeout=timeout_seconds)
        except TimeoutError:
            return False, False

    async with BleakClient(matched_device[0], timeout=10.0) as client:
        return True, bool(client.is_connected)


def probe_mdoc_ble_link(
    raw_qr: bytes,
    *,
    consent: bool,
    decode_cbor: Callable[[bytes], Any] | None = None,
    connect: Callable[[UUID, float], Awaitable[tuple[bool, bool]]] | None = None,
    timeout_seconds: float = _SCAN_WINDOW_SECONDS,
) -> dict[str, object]:
    """Devuelve únicamente estados categóricos. Nunca comparte QR, UUID o MAC."""
    report = _report()
    if not consent:
        report["link_status"] = "consent_required"
        return report
    if not 3 <= timeout_seconds <= 30:
        report["link_status"] = "invalid_timeout"
        return report

    decode = decode_cbor or _load_cbor
    try:
        state, peripheral, central, service_uuid = _get_transport_options(raw_qr, decode_cbor=decode)
    except (ImportError, ModuleNotFoundError):
        report["link_status"] = "cbor2_not_installed"
        return report
    except Exception:
        report["link_status"] = "invalid_cbor"
        return report
    report["link_status"] = state
    report["holder_peripheral_announced"] = peripheral
    report["holder_central_announced"] = central
    report["ble_service_uuid_present"] = service_uuid is not None

    if service_uuid is None:
        return report

    bridge = connect or _connect_to_qr_service
    try:
        found, connected = asyncio.run(
            asyncio.wait_for(bridge(service_uuid, timeout_seconds), timeout=timeout_seconds + 15.0)
        )
    except ImportError as exc:
        report["link_status"] = classify_ble_import_error(exc)
        return report
    except (TimeoutError, asyncio.TimeoutError):
        report["link_status"] = "connection_timeout"
        return report
    except Exception:
        # No revelar excepciones BLE: pueden incluir nombres, UUID o direcciones.
        report["link_status"] = "bluetooth_connection_error"
        return report

    if not found:
        report["link_status"] = "service_not_found"
    elif not connected:
        report["link_status"] = "connection_not_established"
    else:
        report["link_status"] = "link_opened_then_closed"
        report["ble_link_established"] = True
        report["gatt_link_tested"] = True
    return report
