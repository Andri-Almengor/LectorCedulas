"""Flujo cifrado mDoc de laboratorio con elementos totalmente sintéticos."""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from types import SimpleNamespace
from uuid import UUID

import cbor2
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tools.idc_diagnostic.ble_session_lab import (
    _LAB_DOC_TYPE,
    _LAB_ELEMENT,
    _LAB_NAMESPACE,
    _ble_exchange,
    _flags,
    _inspect_reply,
    probe_synthetic_mdoc_transport,
)
from tools.idc_diagnostic.gatt_codec import (
    CLIENT_TO_SERVER_UUID,
    SERVER_TO_CLIENT_UUID,
    STATE_END,
    STATE_START,
    STATE_UUID,
    fragment_message,
)
from tools.idc_diagnostic.mdoc_core import (
    SessionCipherState,
    build_session_establishment,
    prepare_reader_session,
)

UUID_TEST = UUID("6fa459a1-6bd5-486b-8b59-1c375ee613d1")


def _valid_qr() -> bytes:
    device = ec.generate_private_key(ec.SECP256R1())
    point = device.public_key().public_numbers()
    cose = {
        1: 2, -1: 1,
        -2: point.x.to_bytes(32, "big"),
        -3: point.y.to_bytes(32, "big"),
    }
    root = {
        0: "1.0",
        1: [1, cbor2.CBORTag(24, cbor2.dumps(cose))],
        2: [[2, 1, {0: True, 1: False, 10: UUID_TEST.bytes}]],
        3: [],
    }
    raw = cbor2.dumps(root)
    return b"mdoc:" + base64.urlsafe_b64encode(raw).rstrip(b"=")


async def _successful_mock(uuid: UUID, window: float, packet: bytes, cipher: SessionCipherState):
    assert uuid == UUID_TEST and window == 30
    assert cipher.establishment_sent is True
    assert packet == packet[:]
    assert b"nonexistent_test_attribute" not in packet  # request stays encrypted
    assert b"org.example.idc.transport.lab" not in packet
    return {
        **_flags(),
        "device_found": True, "ble_connected": True,
        "gatt_service_found": True, "gatt_properties_match": True,
        "notifications_subscribed": True, "state_start_sent": True,
        "session_establishment_sent": True, "encrypted_request_transmitted": True,
        "response_fragment_seen": True, "session_data_received": True,
        "encrypted_reply_authenticated": True, "state_end_sent": True,
        "notifications_stopped": True,
    }


def test_session_lab_uses_nonexistent_schema_only_and_no_identity():
    assert _LAB_DOC_TYPE.startswith("org.example.")
    assert _LAB_NAMESPACE.startswith("org.example.")
    assert _LAB_ELEMENT.startswith("nonexistent")
    result = probe_synthetic_mdoc_transport(
        _valid_qr(), consent=True, allow_synthetic_exchange=True,
        exchange=_successful_mock,
    )
    assert result["status"] == "encrypted_reply_authenticated_not_identity"
    assert result["reader_keys_derived_locally"] is True
    assert result["encrypted_session_establishment_prepared"] is True
    assert result["encrypted_reply_authenticated"] is True
    assert result["mdoc_session_established"] is False
    assert result["issuer_signature_verified"] is False
    assert result["device_auth_verified"] is False
    assert result["verified_identity"] is False
    assert str(UUID_TEST) not in json.dumps(result)


@pytest.mark.parametrize("consent,exchange", [(False, False), (True, False), (False, True)])
def test_fails_closed_without_two_explicit_permissions(consent, exchange):
    report = probe_synthetic_mdoc_transport(
        b"secret QR", consent=consent, allow_synthetic_exchange=exchange,
        exchange=_successful_mock,
    )
    assert report["status"] == "consent_and_synthetic_exchange_permission_required"
    assert report["reader_keys_derived_locally"] is False
    assert report["session_establishment_sent"] is False


async def _no_device(_uuid, _duration, _packet, _cipher):
    return _flags()


async def _timeout(_uuid, _duration, _packet, _cipher):
    return {
        **_flags(), "device_found": True, "ble_connected": True,
        "gatt_service_found": True, "gatt_properties_match": True,
        "notifications_subscribed": True, "state_start_sent": True,
        "session_establishment_sent": True, "encrypted_request_transmitted": True,
        "response_timeout": True, "state_end_sent": True,
    }


async def _holder_end(_uuid, _duration, _packet, _cipher):
    return {
        **_flags(), "device_found": True, "ble_connected": True,
        "gatt_service_found": True, "gatt_properties_match": True,
        "notifications_subscribed": True, "state_start_sent": True,
        "session_establishment_sent": True, "encrypted_request_transmitted": True,
        "holder_end_observed": True, "state_end_sent": True,
    }


@pytest.mark.parametrize("mock,status", [
    (_no_device, "service_not_found"),
    (_timeout, "no_response_to_synthetic_document_request"),
    (_holder_end, "holder_ended_session_after_synthetic_request"),
])
def test_sanitized_transport_outcomes(mock, status):
    report = probe_synthetic_mdoc_transport(
        _valid_qr(), consent=True, allow_synthetic_exchange=True,
        exchange=mock,
    )
    assert report["status"] == status
    assert report["verified_identity"] is False


def test_reply_authenticated_but_identity_never_verified():
    material = prepare_reader_session(_valid_qr())
    cipher = SessionCipherState(material)
    fake_response = cbor2.dumps({
        "version": "1.0",
        "status": 0,
        "documents": [
            {"sensitive_personal_data": "DO NOT LEAK THIS"},
        ],
    })
    ciphertext = AESGCM(material.sk_device).encrypt(
        b"\x00" * 7 + b"\x01" + (1).to_bytes(4, "big"),
        fake_response, None,
    )
    envelope = cbor2.dumps({"data": ciphertext})
    details = _inspect_reply(envelope, cipher)
    assert details["encrypted_reply_authenticated"] is True
    assert details["device_response_cbor_present"] is True
    assert details["session_data_received"] is True
    assert "sensitive_personal_data" not in json.dumps(details)
    assert "DO NOT LEAK THIS" not in json.dumps(details)


def test_reply_rejects_tampered_encrypted_message():
    material = prepare_reader_session(_valid_qr())
    cipher = SessionCipherState(material)
    ciphertext = bytearray(AESGCM(material.sk_device).encrypt(
        b"\x00" * 7 + b"\x01" + (1).to_bytes(4, "big"),
        cbor2.dumps({"version": "1.0", "status": 0}), None,
    ))
    ciphertext[-1] ^= 0x01
    result = _inspect_reply(cbor2.dumps({"data": bytes(ciphertext)}), cipher)
    assert result["session_data_received"] is True
    assert result["encrypted_reply_authenticated"] is False
    assert cipher.device_counter == 0


def test_real_transport_path_sends_just_one_encrypted_request(monkeypatch):
    qr = _valid_qr()
    material = prepare_reader_session(qr)
    cipher = SessionCipherState(material)
    fake_request = cbor2.dumps({"version": "1.0", "docRequests": [
        {"itemsRequest": cbor2.CBORTag(24, cbor2.dumps({
            "docType": _LAB_DOC_TYPE,
            "nameSpaces": {_LAB_NAMESPACE: {_LAB_ELEMENT: False}},
        }))}
    ]})
    packet = build_session_establishment(material, cipher, fake_request)
    trace = []
    callbacks = {}
    service_uuid = str(UUID_TEST)
    chars = [
        SimpleNamespace(uuid=STATE_UUID, properties=["notify", "write-without-response"]),
        SimpleNamespace(uuid=CLIENT_TO_SERVER_UUID, properties=["write-without-response"]),
        SimpleNamespace(uuid=SERVER_TO_CLIENT_UUID, properties=["notify"]),
    ]
    encrypted = AESGCM(material.sk_device).encrypt(
        b"\x00" * 7 + b"\x01" + (1).to_bytes(4, "big"),
        cbor2.dumps({"version": "1.0", "status": 0, "documents": []}), None,
    )
    session_data = cbor2.dumps({"data": encrypted})

    class Scanner:
        def __init__(self, *, detection_callback, service_uuids, scanning_mode):
            assert service_uuids == [service_uuid] and scanning_mode == "active"
            self.cb = detection_callback

        async def __aenter__(self):
            self.cb(
                SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="private"),
                SimpleNamespace(service_uuids=[service_uuid]),
            )
            return self

        async def __aexit__(self, *_args):
            return None

    class Client:
        def __init__(self, *_args, **_kwargs):
            self.is_connected = True
            self.services = SimpleNamespace(
                get_service=lambda target: SimpleNamespace(characteristics=chars)
                if target == service_uuid else None
            )

        async def __aenter__(self):
            trace.append("connect")
            return self

        async def __aexit__(self, *_args):
            trace.append("disconnect")
            self.is_connected = False

        async def start_notify(self, char, callback):
            trace.append("subscribe:" + char.uuid)
            callbacks[char.uuid] = callback

        async def stop_notify(self, char):
            trace.append("stop:" + char.uuid)

        async def read_gatt_char(self, *_args, **_kwargs):
            pytest.fail("Never read GATT values")

        async def write_gatt_char(self, char, value, *, response):
            assert response is False
            data = bytes(value)
            if char.uuid == STATE_UUID:
                assert data in (STATE_START, STATE_END)
                trace.append("state:" + data.hex())
            else:
                assert char.uuid == CLIENT_TO_SERVER_UUID
                assert data in fragment_message(packet)
                trace.append("fragment")
                if data[0] == 0:
                    for frame in fragment_message(session_data):
                        callbacks[SERVER_TO_CLIENT_UUID](char, bytearray(frame))

    monkeypatch.setitem(sys.modules, "bleak", SimpleNamespace(
        BleakScanner=Scanner, BleakClient=Client
    ))
    monkeypatch.setattr("tools.idc_diagnostic.ble_session_lab._FRAGMENT_SPACING", 0)
    result = asyncio.run(_ble_exchange(UUID_TEST, 3, packet, cipher))
    assert result["encrypted_request_transmitted"] is True
    assert result["encrypted_reply_authenticated"] is True
    assert result["state_end_sent"] is True
    assert trace.index("subscribe:" + STATE_UUID) < trace.index("state:01")
    assert trace.index("subscribe:" + SERVER_TO_CLIENT_UUID) < trace.index("state:01")
    assert trace.index("state:01") < trace.index("fragment")
    assert trace.index("state:02") < trace.index("disconnect")
    assert "private" not in json.dumps(result)
    assert "AA:BB" not in json.dumps(result)


def test_cli_requires_explicit_synthetic_write_permission(monkeypatch):
    from tools.idc_diagnostic.__main__ import main

    def forbidden(*_args, **_kwargs):
        pytest.fail("must not capture QR before consent and opt-in")

    monkeypatch.setattr("tools.idc_diagnostic.__main__.capture_serial", forbidden)
    with pytest.raises(SystemExit):
        main(["--ble-session-lab", "--port", "COM5", "--consent"])


def test_cli_synthetic_session_does_not_print_qr(monkeypatch, capsys):
    from tools.idc_diagnostic.__main__ import main

    monkeypatch.setattr(
        "tools.idc_diagnostic.__main__.capture_serial",
        lambda *_args, **_kwargs: _valid_qr(),
    )
    monkeypatch.setattr(
        "tools.idc_diagnostic.__main__.probe_synthetic_mdoc_transport",
        lambda qr, **_kwargs: {"status": "no_response_to_synthetic_document_request",
                                "verified_identity": False},
    )
    assert main([
        "--ble-session-lab", "--port", "COM5", "--consent",
        "--allow-synthetic-exchange", "--ble-scan-seconds", "30",
    ]) == 0
    printed = capsys.readouterr().out
    assert "no_response_to_synthetic_document_request" in printed
    assert "mdoc:" not in printed


async def _synthetic_document_error(_uuid, _duration, _packet, _cipher):
    # Respuesta fiel al patrón observado en laboratorio: status general 0,
    # documentErrors no vacío y ausencia de documentos.
    return {
        **_flags(),
        "device_found": True,
        "ble_connected": True,
        "gatt_service_found": True,
        "gatt_properties_match": True,
        "notifications_subscribed": True,
        "state_start_sent": True,
        "session_establishment_sent": True,
        "encrypted_request_transmitted": True,
        "response_fragment_seen": True,
        "session_data_received": True,
        "encrypted_reply_authenticated": True,
        "device_response_cbor_present": True,
        "response_status_code": 0,
        "response_status_category": "ok",
        "response_document_count_category": "absent",
        "response_document_errors_present": True,
        "state_end_sent": True,
        "notifications_stopped": True,
    }


def test_authenticated_synthetic_document_error_does_not_look_like_verified_idc():
    report = probe_synthetic_mdoc_transport(
        _valid_qr(), consent=True, allow_synthetic_exchange=True,
        exchange=_synthetic_document_error,
    )
    assert report["synthetic_document_unavailable_observed"] is True
    assert report["status"] == "synthetic_document_unavailable_not_verified"
    assert report["encrypted_reply_authenticated"] is True
    assert report["response_status_code"] == 0
    assert report["response_document_errors_present"] is True
    assert report["response_document_count_category"] == "absent"
    assert report["issuer_signature_verified"] is False
    assert report["device_auth_verified"] is False
    assert report["iaca_trust_anchor_validated"] is False
    assert report["verified_identity"] is False
    assert report["idc_verification_available"] is False


def test_encrypted_reply_without_specific_document_error_stays_generic():
    report = probe_synthetic_mdoc_transport(
        _valid_qr(), consent=True, allow_synthetic_exchange=True,
        exchange=_successful_mock,
    )
    assert report["synthetic_document_unavailable_observed"] is False
    assert report["status"] == "encrypted_reply_authenticated_not_identity"
