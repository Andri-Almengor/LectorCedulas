"""Transporte BLE de laboratorio con petición mDoc sintética no coincidente.

Esta fase NO solicita atributos de una identidad real. El docType y la
selección de campos se fijan a valores org.example irreales que nunca deben
publicarse como credenciales legítimas. Solo devuelve indicadores booleanos;
no imprime QR, claves, respuestas ni valores GATT.

La recepción de SessionData NO valida IssuerAuth, DeviceAuth ni la identidad.
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
    STATE_END,
    STATE_START,
    STATE_UUID,
    GattCodecError,
    GattReassembler,
    fragment_message,
)
from .device_response_shape import classify_device_response_structure
from .mdl_response_shape import inspect_mdl_shape
from .device_mac_precheck import inspect_mac_consistency
from .mdoc_core import (
    MdocProtocolError,
    SessionCipherState,
    _cbor_full,
    build_device_request,
    build_session_establishment,
    prepare_reader_session,
)

# Este tipo de documento no representa ninguna identidad costarricense.
# Se conserva idéntico en pruebas y producción: prohibido personalizarlo
# mediante parámetros CLI, archivos de configuración o variables de entorno.
_LAB_DOC_TYPE = "org.example.idc.transport.lab.nonexistent.1"
_LAB_NAMESPACE = "org.example.idc.transport.lab"
_LAB_ELEMENT = "nonexistent_test_attribute"
_RESPONSE_WINDOW = 12.0
_FRAGMENT_SPACING = 0.035
_SAFE_MTU = 23  # ATT write = 20 bytes; cada trama incluye flag de 1 byte.


def _flags() -> dict[str, bool]:
    return {
        "device_found": False,
        "ble_connected": False,
        "gatt_service_found": False,
        "gatt_properties_match": False,
        "notifications_subscribed": False,
        "state_start_sent": False,
        "session_establishment_sent": False,
        "encrypted_request_transmitted": False,
        "response_fragment_seen": False,
        "session_data_received": False,
        "session_status_received": False,
        "session_data_field_present": False,
        "encrypted_reply_authenticated": False,
        "decrypted_response_shape_recognized": False,
        "device_response_cbor_present": False,
        "holder_end_observed": False,
        "response_timeout": False,
        "invalid_fragment_received": False,
        "state_end_sent": False,
        "notifications_stopped": False,
    }


def classify_document_error_codes(value: Any) -> str:
    """Categorías fijas; nunca devolver identificadores ni códigos privados."""
    if not isinstance(value, dict):
        return "unavailable"
    errors = value.get("documentErrors")
    if errors is None or errors == []:
        return "absent"
    if not isinstance(errors, list) or not 1 <= len(errors) <= 16:
        return "malformed"
    codes = []
    for entry in errors:
        if not isinstance(entry, dict) or not 1 <= len(entry) <= 16:
            return "malformed"
        for doc_type, code in entry.items():
            if not isinstance(doc_type, str) or not doc_type or type(code) is not int:
                return "malformed"
            codes.append(code)
    if all(code == 0 for code in codes):
        return "data_not_returned"
    return "nonzero_document_error"


def _inspect_reply(envelope_bytes: bytes, cipher: SessionCipherState) -> dict[str, bool]:
    """Inspección extremadamente limitada de forma. No extrae ni retorna datos."""
    result = {
        "session_data_received": False,
        "session_status_received": False,
        "session_data_field_present": False,
        "encrypted_reply_authenticated": False,
        "decrypted_response_shape_recognized": False,
        "device_response_cbor_present": False,
        **classify_device_response_structure(None),
        "response_document_error_category": "unavailable",
    }
    try:
        value = _cbor_full(envelope_bytes)
    except Exception:
        return result
    if not isinstance(value, dict) or not (
        isinstance(value.get("data"), bytes)
        or isinstance(value.get("status"), int)
    ):
        return result
    result["session_data_received"] = True
    result["session_status_received"] = (
        type(value.get("status")) is int and 0 <= value["status"] < 256
    )
    encrypted = value.get("data")
    result["session_data_field_present"] = isinstance(encrypted, bytes)
    if not isinstance(encrypted, bytes):
        return result
    try:
        # Este paso confirma que el titular conoce la clave efímera de la
        # sesión, NO que sea una identidad genuina ni que la firma sea válida.
        plaintext = cipher.decrypt_device_message(encrypted)
    except Exception:
        return result
    result["encrypted_reply_authenticated"] = True
    try:
        parsed = _cbor_full(plaintext)
    except Exception:
        return result
    if isinstance(parsed, dict):
        result["decrypted_response_shape_recognized"] = True
        # Solo analizar cabeceras estructurales y el conteo de documentos.
        # Nunca devolver documentos, issuerSigned, deviceSigned ni atributos.
        categorization = classify_device_response_structure(parsed)
        result.update(categorization)
        result["response_document_error_category"] = classify_document_error_codes(parsed)
        result.update(inspect_mdl_shape(parsed))
        result.update(inspect_mac_consistency(parsed, cipher.material))
        result["device_response_cbor_present"] = (
            categorization["response_structure_acceptable"] is True
        )
    return result


async def _ble_exchange(
    service_uuid: UUID, scan_seconds: float, packet: bytes,
    cipher: SessionCipherState,
) -> dict[str, bool]:
    from bleak import BleakClient, BleakScanner

    result = _flags()
    selected: list[Any] = []
    advertised = asyncio.Event()
    target = str(service_uuid).casefold()

    def device_seen(device: Any, adv: Any) -> None:
        ids = getattr(adv, "service_uuids", ()) or ()
        if not selected and any(str(uid).casefold() == target for uid in ids):
            selected.append(device)
            advertised.set()

    async with BleakScanner(
        detection_callback=device_seen,
        service_uuids=[str(service_uuid)],
        scanning_mode="active",
    ):
        try:
            await asyncio.wait_for(advertised.wait(), timeout=scan_seconds)
        except TimeoutError:
            return result

    result["device_found"] = True
    async with BleakClient(selected[0], timeout=10.0) as client:
        if not client.is_connected:
            return result
        result["ble_connected"] = True
        service = client.services.get_service(str(service_uuid))
        if service is None:
            return result
        result["gatt_service_found"] = True
        chars = {str(c.uuid).casefold(): c for c in service.characteristics}
        state = chars.get(STATE_UUID)
        tx = chars.get(CLIENT_TO_SERVER_UUID)
        rx = chars.get(SERVER_TO_CLIENT_UUID)
        if state is None or tx is None or rx is None:
            return result
        sp = {str(prop).casefold() for prop in (state.properties or [])}
        tp = {str(prop).casefold() for prop in (tx.properties or [])}
        rp = {str(prop).casefold() for prop in (rx.properties or [])}
        if not (
            "notify" in sp and "write-without-response" in sp
            and "write-without-response" in tp and "notify" in rp
        ):
            return result
        result["gatt_properties_match"] = True

        complete = asyncio.Event()
        reassembler = GattReassembler(max_bytes=65536)
        incoming: list[bytes] = []
        subscribed_state = False
        subscribed_rx = False

        def state_notification(_characteristic: Any, data: bytearray) -> None:
            if bytes(data) == STATE_END:
                result["holder_end_observed"] = True
                complete.set()

        def response_notification(_characteristic: Any, data: bytearray) -> None:
            result["response_fragment_seen"] = True
            if incoming or result["invalid_fragment_received"]:
                return
            try:
                joined = reassembler.accept(bytes(data))
            except (GattCodecError, ValueError):
                result["invalid_fragment_received"] = True
                complete.set()
                return
            if joined is not None:
                incoming.append(joined)
                complete.set()

        try:
            await client.start_notify(state, state_notification)
            subscribed_state = True
            await client.start_notify(rx, response_notification)
            subscribed_rx = True
            result["notifications_subscribed"] = True

            await client.write_gatt_char(state, STATE_START, response=False)
            result["state_start_sent"] = True
            # Conservador en Windows: 23 bytes ATT MTU, escribir <=20
            # bytes (bandera+19), evitando suponer MTU negociado.
            for fragment in fragment_message(packet, mtu=_SAFE_MTU):
                if not client.is_connected or result["holder_end_observed"]:
                    break
                await client.write_gatt_char(tx, fragment, response=False)
                await asyncio.sleep(_FRAGMENT_SPACING)
            else:
                result["session_establishment_sent"] = True
                result["encrypted_request_transmitted"] = True

            if result["session_establishment_sent"] and not complete.is_set():
                try:
                    await asyncio.wait_for(complete.wait(), timeout=_RESPONSE_WINDOW)
                except TimeoutError:
                    result["response_timeout"] = True

            if incoming:
                inspection = _inspect_reply(incoming.pop(), cipher)
                result.update(inspection)
        finally:
            if result["state_start_sent"] and client.is_connected:
                try:
                    await client.write_gatt_char(state, STATE_END, response=False)
                    result["state_end_sent"] = True
                except Exception:
                    # El titular puede finalizar la conexión.
                    pass
            all_stopped = True
            if subscribed_rx and client.is_connected:
                try:
                    await client.stop_notify(rx)
                except Exception:
                    all_stopped = False
            if subscribed_state and client.is_connected:
                try:
                    await client.stop_notify(state)
                except Exception:
                    all_stopped = False
            result["notifications_stopped"] = all_stopped and client.is_connected
    return result


def probe_synthetic_mdoc_transport(
    raw_qr: bytes,
    *,
    consent: bool,
    allow_synthetic_exchange: bool,
    timeout_seconds: float = 30.0,
    exchange: Callable[
        [UUID, float, bytes, SessionCipherState],
        Awaitable[dict[str, bool]],
    ] | None = None,
) -> dict[str, object]:
    """Transmite petición de docType ficticio. No interpreta identidad."""
    report: dict[str, object] = {
        "schema_version": 1,
        "purpose": "synthetic_mdoc_encrypted_ble_transport_test_only",
        "holder_peripheral_announced": False,
        "ble_service_uuid_present": False,
        "synthetic_unknown_document_type_only": True,
        "no_real_identity_attributes_requested": True,
        "reader_keys_derived_locally": False,
        "encrypted_session_establishment_prepared": False,
        **_flags(),
        **classify_device_response_structure(None),
        "synthetic_document_unavailable_observed": False,
        "mdoc_session_established": False,
        "issuer_signature_verified": False,
        "device_auth_verified": False,
        "iaca_trust_anchor_validated": False,
        "verified_identity": False,
        "idc_verification_available": False,
        "status": "consent_and_synthetic_exchange_permission_required",
    }
    if not consent or not allow_synthetic_exchange:
        return report
    if not 3 <= timeout_seconds <= 30:
        report["status"] = "invalid_timeout"
        return report
    try:
        state, peripheral, _central, service_uuid = _get_transport_options(
            raw_qr, decode_cbor=_load_cbor,
        )
    except ImportError:
        report["status"] = "cbor2_not_installed"
        return report
    except Exception:
        report["status"] = "invalid_or_unsupported_engagement"
        return report
    report["holder_peripheral_announced"] = peripheral
    report["ble_service_uuid_present"] = service_uuid is not None
    if service_uuid is None:
        report["status"] = state
        return report

    try:
        material = prepare_reader_session(raw_qr)
        cipher = SessionCipherState(material)
        request = build_device_request(
            doc_type=_LAB_DOC_TYPE,
            requested_namespaces={_LAB_NAMESPACE: (_LAB_ELEMENT,)},
        )
        packet = build_session_establishment(material, cipher, request)
        report["reader_keys_derived_locally"] = True
        report["encrypted_session_establishment_prepared"] = True
    except MdocProtocolError as exc:
        report["status"] = exc.code
        return report
    except ImportError:
        report["status"] = "optional_crypto_dependency_missing"
        return report
    except Exception:
        report["status"] = "crypto_preparation_error"
        return report

    try:
        results = asyncio.run(asyncio.wait_for(
            (exchange or _ble_exchange)(service_uuid, timeout_seconds, packet, cipher),
            timeout=timeout_seconds + _RESPONSE_WINDOW + 25.0,
        ))
    except ImportError as exc:
        report["status"] = classify_ble_import_error(exc)
        return report
    except TimeoutError:
        report["status"] = "ble_exchange_timeout"
        return report
    except Exception:
        report["status"] = "ble_exchange_error"
        return report
    fields = _flags()
    if not isinstance(results, dict) or any(
        field not in results or type(results[field]) is not bool for field in fields
    ):
        report["status"] = "invalid_transport_probe_result"
        return report
    for field in fields:
        report[field] = results[field]

    # Únicamente copiar etiquetas tipadas ya saneadas y conocidas.
    summary_template = classify_device_response_structure(None)
    for field in summary_template:
        value = results.get(field)
        if field == "response_status_code":
            if type(value) is int and 0 <= value <= 255:
                report[field] = value
        elif field == "response_status_category":
            if value in ("unavailable", "ok", "nonzero", "invalid_or_missing"):
                report[field] = value
        elif field == "response_document_count_category":
            if value in ("unavailable", "absent", "none", "one", "multiple", "invalid"):
                report[field] = value
        elif type(value) is bool:
            report[field] = value

    # Status 0 indica procesamiento general, NO documento presente ni válido.
    # La solicitud es deliberadamente ficticia; errores por documento sin
    # Documents constituyen una respuesta esperada y sin identidad.
    report["synthetic_document_unavailable_observed"] = bool(
        report["encrypted_reply_authenticated"]
        and report["response_status_code"] == 0
        and report["response_document_errors_present"]
        and report["response_document_count_category"] in ("absent", "none")
    )

    if not report["device_found"]:
        report["status"] = "service_not_found"
    elif not report["ble_connected"]:
        report["status"] = "ble_connection_failed"
    elif not report["gatt_properties_match"]:
        report["status"] = "gatt_profile_incomplete"
    elif not report["state_start_sent"]:
        report["status"] = "gatt_state_start_failed"
    elif not report["session_establishment_sent"]:
        report["status"] = "encrypted_request_not_fully_sent"
    elif report["synthetic_document_unavailable_observed"]:
        report["status"] = "synthetic_document_unavailable_not_verified"
    elif report["encrypted_reply_authenticated"]:
        report["status"] = "encrypted_reply_authenticated_not_identity"
    elif report["session_data_received"]:
        report["status"] = "session_data_received_not_authenticated"
    elif report["holder_end_observed"]:
        report["status"] = "holder_ended_session_after_synthetic_request"
    elif report["invalid_fragment_received"]:
        report["status"] = "invalid_ble_response_fragment"
    elif report["response_timeout"]:
        report["status"] = "no_response_to_synthetic_document_request"
    else:
        report["status"] = "synthetic_request_sent_no_authenticated_reply"
    return report
