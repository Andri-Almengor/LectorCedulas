"""Certificados y COSE totalmente SINTÉTICOS para prevalidación de IssuerAuth."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import cbor2
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID, ObjectIdentifier

from tools.idc_diagnostic.issuer_auth import (
    issuer_signed_item_digest_matches,
    verify_issuer_auth_signature,
)

NOW = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
DOC = "org.example.sample"
ISSUER_OID = ObjectIdentifier("1.0.18013.5.1.2")


def _key_usage(*, ca: bool) -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=not ca,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=ca,
        crl_sign=ca,
        encipher_only=None,
        decipher_only=None,
    )


def _make_chain(*, wrong_leaf_country: bool = False):
    root_key = ec.generate_private_key(ec.SECP256R1())
    root_name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CR"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic IACA for tests"),
    ])
    iaca = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(days=90))
        .not_valid_after(NOW + timedelta(days=90))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(_key_usage(ca=True), critical=True)
        .sign(root_key, hashes.SHA256())
    )
    ds_key = ec.generate_private_key(ec.SECP256R1())
    ds_name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "PA" if wrong_leaf_country else "CR"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic Document Signer"),
    ])
    ds = (
        x509.CertificateBuilder()
        .subject_name(ds_name)
        .issuer_name(root_name)
        .public_key(ds_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(days=20))
        .not_valid_after(NOW + timedelta(days=20))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(_key_usage(ca=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ISSUER_OID]), critical=True)
        .sign(root_key, hashes.SHA256())
    )
    return iaca.public_bytes(Encoding.DER), ds.public_bytes(Encoding.DER), ds_key


def _sign_mso(
    root_der: bytes,
    leaf_der: bytes,
    leaf_private,
    *,
    doc_type: str = DOC,
    valid_until: str = "2026-12-10T00:00:00Z",
):
    mso = {
        "version": "1.0",
        "digestAlgorithm": "SHA-256",
        "docType": doc_type,
        "valueDigests": {"org.example.person": {}},
        "validityInfo": {
            "signed": "2026-11-01T00:00:00Z",
            "validFrom": "2026-11-02T00:00:00Z",
            "validUntil": valid_until,
        },
    }
    protected = cbor2.dumps({1: -7})
    payload = cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps(mso)))
    structure = cbor2.dumps(["Signature1", protected, b"", payload])
    der_sig = leaf_private.sign(structure, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der_sig)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return cbor2.dumps(cbor2.CBORTag(18, [protected, {33: [leaf_der]}, payload, signature]))


def test_issuer_signature_and_direct_iaca_chain_are_prechecked_not_identity():
    root, leaf, ds_key = _make_chain()
    auth = _sign_mso(root, leaf, ds_key)
    result = verify_issuer_auth_signature(auth, trusted_iaca_der=root, expected_doc_type=DOC, when=NOW)
    assert result["status"] == "issuer_auth_partial_precheck_passed_not_identity"
    assert result["trusted_iaca_chain_valid"] is True
    assert result["issuer_signature_valid"] is True
    assert result["mso_doc_type_valid"] is True
    assert result["mso_time_valid"] is True
    assert result["all_issuer_item_digests_verified"] is False
    assert result["device_auth_verified"] is False
    assert result["certificate_revocation_checked"] is False
    assert result["verified_identity"] is False
    assert root.hex() not in json.dumps(result)


def test_missing_iaca_fail_closed():
    root, leaf, ds_key = _make_chain()
    auth = _sign_mso(root, leaf, ds_key)
    result = verify_issuer_auth_signature(auth, trusted_iaca_der=None, expected_doc_type=DOC, when=NOW)
    assert result["status"] == "trusted_iaca_required"
    assert result["issuer_signature_valid"] is False


def test_wrong_trust_root_rejected():
    root, leaf, ds_key = _make_chain()
    wrong_root, _, _ = _make_chain()
    auth = _sign_mso(root, leaf, ds_key)
    result = verify_issuer_auth_signature(auth, trusted_iaca_der=wrong_root, expected_doc_type=DOC, when=NOW)
    assert result["status"] == "invalid_certificate_chain"
    assert result["trusted_iaca_chain_valid"] is False
    assert result["verified_identity"] is False


def test_invalid_signature_is_rejected():
    root, leaf, ds_key = _make_chain()
    raw = _sign_mso(root, leaf, ds_key)
    sign1 = cbor2.loads(raw)
    fields = sign1.value
    corrupted = bytearray(fields[3])
    corrupted[0] ^= 0x04
    bad = cbor2.dumps(cbor2.CBORTag(18, [*fields[:3], bytes(corrupted)]))
    report = verify_issuer_auth_signature(bad, trusted_iaca_der=root, expected_doc_type=DOC, when=NOW)
    assert report["status"] == "invalid_issuer_signature"
    assert report["verified_identity"] is False


def test_wrong_document_type_is_rejected():
    root, leaf, ds_key = _make_chain()
    raw = _sign_mso(root, leaf, ds_key)
    report = verify_issuer_auth_signature(
        raw, trusted_iaca_der=root, expected_doc_type="org.example.different", when=NOW
    )
    assert report["status"] == "doc_type_mismatch"
    assert report["issuer_signature_valid"] is True
    assert report["verified_identity"] is False


def test_expired_mso_is_rejected():
    root, leaf, ds_key = _make_chain()
    raw = _sign_mso(root, leaf, ds_key, valid_until="2026-11-20T00:00:00Z")
    report = verify_issuer_auth_signature(raw, trusted_iaca_der=root, expected_doc_type=DOC, when=NOW)
    assert report["status"] == "invalid_mso_validity"
    assert report["verified_identity"] is False


def test_signer_country_must_equal_iaca_country():
    root, leaf, ds_key = _make_chain(wrong_leaf_country=True)
    raw = _sign_mso(root, leaf, ds_key)
    report = verify_issuer_auth_signature(raw, trusted_iaca_der=root, expected_doc_type=DOC, when=NOW)
    assert report["status"] == "issuer_country_mismatch"
    assert report["verified_identity"] is False


def test_issuer_signed_item_digest_matches_raw_tag24():
    item = cbor2.CBORTag(24, cbor2.dumps({
        "digestID": 0, "random": b"synthetic", "elementIdentifier": "family_name",
        "elementValue": "TEST_PERSON",
    }))
    digest = hashlib.sha256(cbor2.dumps(item)).digest()
    assert issuer_signed_item_digest_matches(item, digest) is True
    changed = cbor2.CBORTag(24, cbor2.dumps({
        "digestID": 0, "random": b"synthetic", "elementIdentifier": "family_name",
        "elementValue": "TAMPERED",
    }))
    assert issuer_signed_item_digest_matches(changed, digest) is False
    assert issuer_signed_item_digest_matches(item, b"short") is False


@pytest.mark.parametrize("invalid", [b"", b"\x81", b"\x80", b"not cbor"])
def test_invalid_cose_fails_closed(invalid):
    report = verify_issuer_auth_signature(
        invalid, trusted_iaca_der=b"synthetic", expected_doc_type=DOC, when=NOW
    )
    assert report["verified_identity"] is False
    assert report["issuer_signature_valid"] is False
    assert report["status"] != "issuer_auth_partial_precheck_passed_not_identity"
