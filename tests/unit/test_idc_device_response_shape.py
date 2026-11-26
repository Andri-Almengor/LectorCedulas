"""Diagnóstico de forma de respuesta cifrada sin divulgación de datos de identidad."""
from __future__ import annotations

import base64
import json

import cbor2
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tools.idc_diagnostic.ble_session_lab import _inspect_reply
from tools.idc_diagnostic.device_response_shape import classify_device_response_structure
from tools.idc_diagnostic.mdoc_core import SessionCipherState, prepare_reader_session


def _synthetic_session() -> SessionCipherState:
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_numbers()
    cose = {
        1: 2, -1: 1,
        -2: pub.x.to_bytes(32, "big"), -3: pub.y.to_bytes(32, "big"),
    }
    engagement = {
        0: "1.0",
        1: [1, cbor2.CBORTag(24, cbor2.dumps(cose))],
        2: [[2, 1, {0: True, 1: False,
                     10: bytes.fromhex("6fa459a16bd5486b8b591c375ee613d1")}]],
    }
    qr = b"mdoc:" + base64.urlsafe_b64encode(cbor2.dumps(engagement)).rstrip(b"=")
    return SessionCipherState(prepare_reader_session(qr))


def _authenticated_response(cipher: SessionCipherState, response: dict) -> dict[str, object]:
    encrypted = AESGCM(cipher.material.sk_device).encrypt(
        b"\x00" * 7 + b"\x01" + (1).to_bytes(4, "big"),
        cbor2.dumps(response),
        None,
    )
    return _inspect_reply(cbor2.dumps({"data": encrypted}), cipher)


def test_empty_response_classified_without_credential():
    result = classify_device_response_structure(
        {"version": "1.0", "status": 0, "documents": [], "documentErrors": []}
    )
    assert result["response_status_code"] == 0
    assert result["response_status_category"] == "ok"
    assert result["response_document_count_category"] == "none"
    assert result["response_document_errors_present"] is False
    assert result["response_unexpected_document_present"] is False
    assert result["response_structure_acceptable"] is True


def test_document_errors_visible_only_as_boolean_not_as_data():
    doc_type = "com.sensitive.real.type.not.printed"
    payload = {"version": "1.0", "status": 0, "documentErrors": [{doc_type: 0}]}
    result = classify_device_response_structure(payload)
    assert result["response_document_count_category"] == "absent"
    assert result["response_document_errors_present"] is True
    assert result["response_unexpected_document_present"] is False
    assert doc_type not in json.dumps(result)


def test_malformed_status_is_rejected_including_bool_status():
    for status in [None, True, -1, 999, "0"]:
        result = classify_device_response_structure({"version": "1.0", "status": status})
        assert result["response_structure_acceptable"] is False
        assert result["response_status_code"] is None
        assert result["response_status_category"] == "invalid_or_missing"


@pytest.mark.parametrize(
    "documents,expected",
    [
        (None, "absent"),
        ([], "none"),
        ([{"private": "hello"}], "one"),
        ([{"private": "hello"}, {"private": "world"}], "multiple"),
        ({"private": "hello"}, "invalid"),
    ],
)
def test_document_count_only_never_exposes_content(documents, expected):
    payload = {"version": "1.0", "status": 0}
    if documents is not None:
        payload["documents"] = documents
    result = classify_device_response_structure(payload)
    assert result["response_document_count_category"] == expected
    assert result["response_unexpected_document_present"] is (
        expected in ("one", "multiple")
    )
    assert "hello" not in json.dumps(result)
    assert "world" not in json.dumps(result)


def test_decrypt_and_summarize_synthetic_error_reply_without_identity():
    cipher = _synthetic_session()
    code = 0
    payload = {
        "version": "1.0",
        "status": code,
        "documentErrors": [{"org.example.idc.transport.lab.nonexistent.1": 0}],
        "documents": [],
    }
    report = _authenticated_response(cipher, payload)
    assert report["encrypted_reply_authenticated"] is True
    assert report["session_data_field_present"] is True
    assert report["device_response_cbor_present"] is True
    assert report["response_status_code"] == code
    assert report["response_status_category"] == "ok"
    assert report["response_document_errors_present"] is True
    assert report["response_document_count_category"] == "none"
    assert report["response_unexpected_document_present"] is False
    assert "org.example.idc" not in json.dumps(report)


def test_unknown_document_returned_is_flagged_but_content_not_leaked():
    cipher = _synthetic_session()
    response = {
        "version": "1.0",
        "status": 0,
        "documents": [{
            "docType": "org.secret.photoid",
            "issuerSigned": {"namespace": "PERSONAL_NAME_DO_NOT_LOG"},
            "deviceSigned": {"deviceAuth": "SECRET_SIG_DO_NOT_LOG"},
        }],
    }
    report = _authenticated_response(cipher, response)
    assert report["response_document_count_category"] == "one"
    assert report["response_unexpected_document_present"] is True
    assert report["encrypted_reply_authenticated"] is True
    assert "PERSONAL_NAME_DO_NOT_LOG" not in json.dumps(report)
    assert "SECRET_SIG_DO_NOT_LOG" not in json.dumps(report)
    assert "org.secret" not in json.dumps(report)


def test_nonzero_status_is_reported_as_code_without_guessing_reason():
    result = classify_device_response_structure({"version": "1.0", "status": 10})
    assert result["response_status_code"] == 10
    assert result["response_status_category"] == "nonzero"
    assert result["response_document_count_category"] == "absent"


def test_tampered_reply_does_not_emit_status_or_document_summary():
    cipher = _synthetic_session()
    encrypted = bytearray(AESGCM(cipher.material.sk_device).encrypt(
        b"\x00" * 7 + b"\x01" + (1).to_bytes(4, "big"),
        cbor2.dumps({"version": "1.0", "status": 0, "documents": []}),
        None,
    ))
    encrypted[-1] ^= 1
    report = _inspect_reply(cbor2.dumps({"data": bytes(encrypted)}), cipher)
    assert report["encrypted_reply_authenticated"] is False
    assert report["response_status_code"] is None
    assert report["response_status_category"] == "unavailable"
    assert report["response_document_count_category"] == "unavailable"


def test_outer_session_status_without_data_is_not_device_response():
    report = _inspect_reply(cbor2.dumps({"status": 20}), _synthetic_session())
    assert report["session_data_received"] is True
    assert report["session_status_received"] is True
    assert report["session_data_field_present"] is False
    assert report["encrypted_reply_authenticated"] is False
    assert report["response_status_code"] is None
