"""QA21: pruebas independientes de consistencia MAC, nunca identidad."""
import hashlib
import hmac
import json

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from tools.idc_diagnostic.device_mac_precheck import DOC, inspect_mac_consistency
from tools.idc_diagnostic.mdl_response_shape import NS, inspect_mdl_shape
from tools.idc_diagnostic.mdoc_core import prepare_reader_session
from test_idc_ble_session_lab import _valid_qr
from test_idc_mdl_response_shape import _response


def _fixture():
    session = prepare_reader_session(_valid_qr())
    device = ec.generate_private_key(ec.SECP256R1())
    p = device.public_key().public_numbers()
    mso = {"version": "1.0", "docType": DOC, "deviceKeyInfo": {"deviceKey": {
        1: 2, -1: 1, -2: p.x.to_bytes(32, "big"), -3: p.y.to_bytes(32, "big"),
    }}}
    response = _response()
    doc = response["documents"][0]
    doc["issuerSigned"]["issuerAuth"] = [
        b"", {}, cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps(mso))), b"not-verified",
    ]
    spaces = cbor2.CBORTag(24, cbor2.dumps({}))
    protected = cbor2.dumps({1: 5})
    transcript = cbor2.loads(cbor2.loads(session.session_transcript).value)
    detached = cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps([
        "DeviceAuthentication", transcript, DOC, spaces,
    ])))
    secret = device.exchange(ec.ECDH(), session.reader_key.public_key())
    emac = HKDF(
        algorithm=hashes.SHA256(), length=32,
        salt=hashlib.sha256(session.session_transcript).digest(), info=b"EMacKey",
    ).derive(secret)
    tag = hmac.digest(emac, cbor2.dumps(["MAC0", protected, b"", detached]), "sha256")
    doc["deviceSigned"] = {
        "nameSpaces": spaces, "deviceAuth": {"deviceMac": [protected, {}, None, tag]},
    }
    return response, session


def test_correct_mac_only_consistent_with_untrusted_key():
    response, session = _fixture()
    result = inspect_mac_consistency(response, session)
    assert result["mdl_mac_consistency_checked"] is True, result
    assert result["mdl_mac_matches_untrusted_mso_key"] is True
    assert "not-verified" not in json.dumps(result)


def test_wrong_session_rejected():
    response, _ = _fixture()
    result = inspect_mac_consistency(response, prepare_reader_session(_valid_qr()))
    assert result["mdl_mac_consistency_checked"] is True
    assert result["mdl_mac_matches_untrusted_mso_key"] is False


def test_wrong_tag_rejected():
    response, session = _fixture()
    mac = response["documents"][0]["deviceSigned"]["deviceAuth"]["deviceMac"]
    mac[3] = bytes([mac[3][0] ^ 1]) + mac[3][1:]
    result = inspect_mac_consistency(response, session)
    assert result["mdl_mac_consistency_checked"] is True
    assert result["mdl_mac_matches_untrusted_mso_key"] is False


@pytest.mark.parametrize("mode", ["empty_tag", "unprotected_alg", "attached", "wrong_alg"])
def test_unsupported_mac_shape(mode):
    response, session = _fixture()
    mac = response["documents"][0]["deviceSigned"]["deviceAuth"]["deviceMac"]
    if mode == "empty_tag":
        mac[3] = b""
    elif mode == "unprotected_alg":
        mac[0], mac[1] = b"", {1: 5}
    elif mode == "attached":
        mac[2] = b""
    else:
        mac[0] = cbor2.dumps({1: 4})
    result = inspect_mac_consistency(response, session)
    assert result["mdl_mac_consistency_checked"] is False
    assert result["mdl_mac_matches_untrusted_mso_key"] is False
    assert result["mdl_mac_tag_empty"] is (mode == "empty_tag")
    assert result["mdl_mac_alg5_unprotected"] is (mode == "unprotected_alg")


@pytest.mark.parametrize("code", [0, -1, True])
def test_country_error_classification(code):
    response = _response()
    response["documents"][0]["errors"] = {NS: {"issuing_country": code}}
    result = inspect_mdl_shape(response)
    assert result["mdl_requested_country_error_present"] is True
    assert result["mdl_requested_country_error_data_not_returned"] is (type(code) is int and code == 0)
    assert result["mdl_requested_country_error_nonzero"] is (type(code) is int and code != 0)
