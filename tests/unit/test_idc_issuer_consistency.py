"""QA23: consistency with an untrusted signer certificate; no real PII."""
import json

import cbor2
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tools.idc_diagnostic.ble_session_lab import _inspect_reply
from tools.idc_diagnostic.issuer_consistency import DOC, inspect_issuer_consistency
from tools.idc_diagnostic.mdoc_core import SessionCipherState, prepare_reader_session
from test_idc_ble_session_lab import _valid_qr
from test_idc_issuer_auth import NOW, _make_chain, _sign_mso


def _response(*, doc_type=DOC, valid_until="2026-12-10T00:00:00Z"):
    root, leaf, key = _make_chain()
    sign1 = cbor2.loads(_sign_mso(root, leaf, key, doc_type=doc_type, valid_until=valid_until))
    parts = list(sign1.value)
    parts[1] = dict(parts[1])
    return {"version": "1.0", "status": 0, "documents": [{
        "docType": DOC, "issuerSigned": {"issuerAuth": parts},
    }]}, root, leaf


def _check(response):
    result = inspect_issuer_consistency(response, when=NOW)
    assert all(type(value) is bool for value in result.values())
    assert "Synthetic Document Signer" not in json.dumps(result)
    assert "verified_identity" not in result
    return result


def test_signature_matches_untrusted_cert():
    response, _, _ = _response()
    result = _check(response)
    for field in (
        "mdl_issuer_es256_supported", "mdl_issuer_x5chain_present",
        "mdl_issuer_signer_cert_decodable", "mdl_issuer_signer_cert_current",
        "mdl_issuer_signer_key_matches_alg", "mdl_issuer_signature_consistency_checked",
        "mdl_issuer_signature_matches_untrusted_cert", "mdl_signed_mso_doc_type_matches",
        "mdl_signed_mso_time_window_current",
    ):
        assert result[field] is True, result


@pytest.mark.parametrize("mode", ["signature", "payload", "wrong_cert"])
def test_rejects_inconsistent_signature(mode):
    response, _, _ = _response()
    parts = response["documents"][0]["issuerSigned"]["issuerAuth"]
    if mode == "wrong_cert":
        parts[1][33] = _make_chain()[1]
    else:
        i = 3 if mode == "signature" else 2
        parts[i] = bytes([parts[i][0] ^ 1]) + parts[i][1:]
    result = _check(response)
    assert result["mdl_issuer_signature_consistency_checked"] is True
    assert result["mdl_issuer_signature_matches_untrusted_cert"] is False
    assert result["mdl_signed_mso_time_window_current"] is False


def test_multiple_certs_are_not_trust():
    response, root, leaf = _response()
    response["documents"][0]["issuerSigned"]["issuerAuth"][1][33] = [leaf, root]
    result = _check(response)
    assert result["mdl_issuer_x5chain_multiple"] is True
    assert result["mdl_issuer_signature_matches_untrusted_cert"] is True
    assert root.hex() not in json.dumps(result)


@pytest.mark.parametrize("mode", ["missing_cert", "duplicate_alg", "unsupported_alg"])
def test_unsupported_headers(mode):
    response, _, _ = _response()
    parts = response["documents"][0]["issuerSigned"]["issuerAuth"]
    if mode == "missing_cert":
        parts[1].clear()
    elif mode == "duplicate_alg":
        parts[1][1] = -7
    else:
        parts[0] = cbor2.dumps({1: 5})
    assert _check(response)["mdl_issuer_signature_consistency_checked"] is False


@pytest.mark.parametrize("mode", ["wrong_doc", "expired"])
def test_signed_mso_checks_are_separate(mode):
    response, _, _ = _response(
        doc_type="org.example.other" if mode == "wrong_doc" else DOC,
        valid_until="2026-11-20T00:00:00Z" if mode == "expired" else "2026-12-10T00:00:00Z",
    )
    result = _check(response)
    assert result["mdl_issuer_signature_matches_untrusted_cert"] is True
    assert result["mdl_signed_mso_doc_type_matches"] is (mode == "expired")
    assert result["mdl_signed_mso_time_window_current"] is False


@pytest.mark.parametrize("tamper", [False, True])
def test_transport_inspects_only_authenticated_response(tamper):
    response, _, _ = _response()
    material = prepare_reader_session(_valid_qr())
    cipher = SessionCipherState(material)
    encrypted = AESGCM(material.sk_device).encrypt(
        b"\x00" * 7 + b"\x01" + (1).to_bytes(4, "big"), cbor2.dumps(response), None,
    )
    if tamper:
        encrypted = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
    result = _inspect_reply(cbor2.dumps({"data": encrypted}), cipher)
    assert result.get("mdl_issuer_signature_matches_untrusted_cert", False) is not tamper
    assert result["encrypted_reply_authenticated"] is not tamper
