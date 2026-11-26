"""Prueba presencial de señalización State BLE mDoc (sin DeviceRequest).

A diferencia de la prueba GATT de solo metadatos, esta prueba se suscribe a
notificaciones y escribe SOLO los bytes públicos Start (0x01), End (0x02) en
State. Nunca escribe Client2Server, ni construye DeviceRequest, ni devuelve
notificaciones o identificadores de dispositivos.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from .ble_link_probe import _get_transport_options, _load_cbor
from .ble_runtime import classify_ble_import_error
from .gatt_codec import (
    CLIENT_TO_SERVER_UUID, SERVER_TO_CLIENT_UUID, STATE_END, STATE_START, STATE_UUID,
)


def _flags() -> dict[str, bool]:
    return {
        "device_found": False,
        "ble_connected": False,
        "gatt_service_found": False,
        "required_properties_present": False,
        "state_notify_subscribed": False,
        "server_to_client_notify_subscribed": False,
        "state_start_sent": False,
        "state_end_sent": False,
        "peer_end_observed": False,
        "unrequested_data_notification_seen": False,
        "notification_unsubscribe_completed": False,
    }


async def _try_state_handshake(service_uuid: UUID, scan_seconds: float) -> dict[str, bool]:
    from bleak import BleakClient, BleakScanner

    result = _flags()
    target = str(service_uuid).casefold()
    chosen: list[Any] = []
    found = asyncio.Event()

    def discovered(device: Any, advertisement: Any) -> None:
        announced = getattr(advertisement, "service_uuids", ()) or ()
        if not chosen and any(str(uid).casefold() == target for uid in announced):
            chosen.append(device)
            found.set()

    async with BleakScanner(
        detection_callback=discovered, service_uuids=[str(service_uuid)],
        scanning_mode="active",
    ):
        try:
            await asyncio.wait_for(found.wait(), timeout=scan_seconds)
        except TimeoutError:
            return result

    result["device_found"] = True

    async with BleakClient(chosen[0], timeout=10.0) as client:
        if not client.is_connected:
            return result
        result["ble_connected"] = True
        service = client.services.get_service(str(service_uuid))
        if service is None:
            return result
        result["gatt_service_found"] = True

        chars = {str(item.uuid).casefold(): item for item in service.characteristics}
        state = chars.get(STATE_UUID)
        client_to_server = chars.get(CLIENT_TO_SERVER_UUID)
        server_to_client = chars.get(SERVER_TO_CLIENT_UUID)

        if state is None or client_to_server is None or server_to_client is None:
            return result

        state_props = {str(p).casefold() for p in (state.properties or [])}
        c2s_props = {str(p).casefold() for p in (client_to_server.properties or [])}
        s2c_props = {str(p).casefold() for p in (server_to_client.properties or [])}
        if not (
            "notify" in state_props
            and "write-without-response" in state_props
            and "notify" in s2c_props
            and "write-without-response" in c2s_props
        ):
            return result
        result["required_properties_present"] = True

        def state_notification(_char: Any, value: bytearray) -> None:
            # No conservar ni imprimir datos de notificación.
            if bytes(value) == STATE_END:
                result["peer_end_observed"] = True

        def server_notification(_char: Any, _value: bytearray) -> None:
            # No reensamblar ni leer respuesta sin DeviceRequest consentido.
            result["unrequested_data_notification_seen"] = True

        try:
            await client.start_notify(state, state_notification)
            result["state_notify_subscribed"] = True
            await client.start_notify(server_to_client, server_notification)
            result["server_to_client_notify_subscribed"] = True

            # ISO/IEC 18013-5: notificaciones activadas ANTES de Start.
            await client.write_gatt_char(state, STATE_START, response=False)
            result["state_start_sent"] = True

            # No enviar DeviceRequest ni leer valores. Ventana breve para observar
            # respuesta de estado, sin prolongar sesión en el teléfono.
            await asyncio.sleep(0.8)
        finally:
            if result["state_start_sent"] and client.is_connected:
                try:
                    await client.write_gatt_char(state, STATE_END, response=False)
                    result["state_end_sent"] = True
                except Exception:
                    pass  # el teléfono puede cerrar la conexión por su cuenta
            all_stopped = True
            if result["server_to_client_notify_subscribed"] and client.is_connected:
                try:
                    await client.stop_notify(server_to_client)
                except Exception:
                    all_stopped = False
            if result["state_notify_subscribed"] and client.is_connected:
                try:
                    await client.stop_notify(state)
                except Exception:
                    all_stopped = False
            if not client.is_connected:
                all_stopped = False
            result["notification_unsubscribe_completed"] = all_stopped
    return result


def probe_mdoc_ble_state(
    raw_qr: bytes,
    *,
    consent: bool,
    allow_gatt_write: bool,
    timeout_seconds: float = 30.0,
    decode_cbor: Callable[[bytes], Any] | None = None,
    handshake: Callable[[UUID, float], Awaitable[dict[str, bool]]] | None = None,
) -> dict[str, object]:
    """Diagnóstico de señalización, nunca constituye sesión ni autenticación."""
    report: dict[str, object] = {
        "schema_version": 1,
        "purpose": "consented_mdoc_gatt_state_signal_probe_only",
        "nearby_scan_scope": "qr_service_uuid_only",
        "holder_peripheral_announced": False,
        "ble_service_uuid_present": False,
        "ble_link_established": False,
        "gatt_service_found": False,
        "required_properties_present": False,
        "state_notify_subscribed": False,
        "server_to_client_notify_subscribed": False,
        "state_start_sent": False,
        "state_end_sent": False,
        "peer_end_observed": False,
        "unrequested_data_notification_seen": False,
        "notification_unsubscribe_completed": False,
        "client_to_server_data_sent": False,
        "device_request_sent": False,
        "mdoc_session_established": False,
        "issuer_signature_verified": False,
        "device_auth_verified": False,
        "verified_identity": False,
        "idc_verification_available": False,
        "status": "consent_and_write_permission_required",
    }
    if not consent or not allow_gatt_write:
        return report
    if not 3 <= timeout_seconds <= 30:
        report["status"] = "invalid_timeout"
        return report

    try:
        state, peripheral, _central, target = _get_transport_options(
            raw_qr, decode_cbor=decode_cbor or _load_cbor,
        )
    except ImportError:
        report["status"] = "cbor2_not_installed"
        return report
    except Exception:
        report["status"] = "invalid_or_unsupported_engagement"
        return report

    report["holder_peripheral_announced"] = peripheral
    report["ble_service_uuid_present"] = target is not None
    if target is None:
        report["status"] = state
        return report
    try:
        details = asyncio.run(
            asyncio.wait_for(
                (handshake or _try_state_handshake)(target, timeout_seconds),
                timeout=timeout_seconds + 20.0,
            )
        )
    except ImportError as exc:
        report["status"] = classify_ble_import_error(exc)
        return report
    except TimeoutError:
        report["status"] = "state_probe_timeout"
        return report
    except Exception:
        report["status"] = "state_probe_error"
        return report

    if not isinstance(details, dict) or any(
        type(v) is not bool for v in details.values()
    ):
        report["status"] = "state_probe_error"
        return report
    for key in _flags():
        report[key] = details.get(key) is True
    report["ble_link_established"] = report["ble_connected"]
    if not report["device_found"]:
        report["status"] = "service_not_found"
    elif not report["ble_connected"]:
        report["status"] = "connection_not_established"
    elif not report["gatt_service_found"]:
        report["status"] = "gatt_service_missing_after_connection"
    elif not report["required_properties_present"]:
        report["status"] = "required_gatt_properties_missing"
    elif not report["state_start_sent"]:
        report["status"] = "state_start_not_sent"
    elif not report["state_end_sent"]:
        report["status"] = "state_start_sent_end_not_confirmed"
    else:
        report["status"] = "state_start_and_end_sent_no_document_request"
    return report
