"""QA19: respuesta sintética con la forma pública mDL, sin PII."""
import json

import cbor2
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tools.idc_diagnostic.ble_session_lab import _inspect_reply
from tools.idc_diagnostic.mdl_response_shape import DOC, NS, inspect_mdl_shape
from tools.idc_diagnostic.mdoc_core import SessionCipherState, prepare_reader_session
from test_idc_ble_session_lab import _valid_qr


def _item(name="issuing_country", value="ZZ", digest_id=0):
    return cbor2.CBORTag(24, cbor2.dumps({
        "digestID": digest_id, "random": b"0123456789abcdef",
        "elementIdentifier": name, "elementValue": value,
    }))


def _response():
    return {
        "version": "1.0", "status": 0, "documents": [{
            "docType": DOC,
            "issuerSigned": {"nameSpaces": {NS: [_item()]}, "issuerAuth": [b"", {}, b"", b""]},
            "deviceSigned": {"deviceAuth": {"deviceSignature": [b"", {}, None, b""]}},
        }],
    }


def test_expected_document_and_country_shape():
    result = inspect_mdl_shape(_response())
    for key in (
        "mdl_returned_doc_type_matches", "mdl_requested_namespace_present", "mdl_issuing_country_present",
        "mdl_issuing_country_shape_valid", "mdl_requested_item_structure_valid",
        "mdl_issuer_auth_present", "mdl_device_signature_present", "mdl_device_signed_present",
    ):
        assert result[key] is True, result
    assert result["mdl_additional_issuer_items_present"] is False
    assert result["mdl_device_mac_present"] is False
    assert "ZZ" not in json.dumps(result)


def test_unexpected_doc_type():
    response = _response()
    response["documents"][0]["docType"] = "org.example.other"
    assert not any(inspect_mdl_shape(response).values())


def test_missing_attribute():
    response = _response()
    response["documents"][0]["issuerSigned"]["nameSpaces"][NS] = [_item("private", "PRIVATE")]
    result = inspect_mdl_shape(response)
    assert result["mdl_issuing_country_present"] is False
    assert result["mdl_requested_item_structure_valid"] is False
    assert result["mdl_additional_issuer_items_present"] is True
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("items", [
    [_item(value="invalid")], [_item(), _item(digest_id=1)], [_item(), _item()],
    [cbor2.CBORTag(24, b"invalid")],
])
def test_malformed_or_duplicate_item(items):
    response = _response()
    response["documents"][0]["issuerSigned"]["nameSpaces"][NS] = items
    assert inspect_mdl_shape(response)["mdl_requested_item_structure_valid"] is False


def test_additional_item_and_device_mac():
    response = _response()
    doc = response["documents"][0]
    doc["issuerSigned"]["nameSpaces"][NS].append(_item("private", "PRIVATE", 1))
    doc["deviceSigned"]["deviceAuth"] = {"deviceMac": [b"", {}, None, b""]}
    result = inspect_mdl_shape(response)
    assert result["mdl_additional_issuer_items_present"] is True
    assert result["mdl_device_mac_present"] is True
    assert result["mdl_device_signature_present"] is False
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("tamper", [False, True])
def test_encrypted_response_shape_only_after_authentication(tamper):
    material = prepare_reader_session(_valid_qr())
    cipher = SessionCipherState(material)
    payload = cbor2.dumps(_response())
    encrypted = AESGCM(material.sk_device).encrypt(
        b"\x00" * 7 + b"\x01" + (1).to_bytes(4, "big"), payload, None,
    )
    if tamper:
        encrypted = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
    result = _inspect_reply(cbor2.dumps({"data": encrypted}), cipher)
    assert result["encrypted_reply_authenticated"] is not tamper
    assert result.get("mdl_requested_item_structure_valid", False) is not tamper
    assert "ZZ" not in json.dumps(result)
