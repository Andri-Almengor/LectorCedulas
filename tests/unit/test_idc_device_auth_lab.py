"""QA14: DeviceSignature de laboratorio, sin datos ni certificados reales."""
import hashlib
import json

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from tools.idc_diagnostic.device_auth_lab import (
    precheck_synthetic_device_auth,
    synthetic_transcript,
)
from tools.idc_diagnostic.signed_items_lab import DOC, NAMESPACE
from test_idc_issuer_auth import NOW, _make_chain
from test_idc_signed_items_lab import _item


def _sign(key, payload, *, header=None, detached=False, cert=None):
    protected = cbor2.dumps({1: -7} if header is None else header)
    der = key.sign(cbor2.dumps(["Signature1", protected, b"", payload]), ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    return cbor2.dumps(cbor2.CBORTag(18, [
        protected, {33: [cert]} if cert else {}, None if detached else payload,
        r.to_bytes(32, "big") + s.to_bytes(32, "big"),
    ]))


def _issuer(leaf, signer, items, device):
    p = device.public_key().public_numbers()
    mso = {
        "version": "1.0", "docType": DOC, "digestAlgorithm": "SHA-256",
        "valueDigests": {NAMESPACE: {i: hashlib.sha256(item).digest() for i, item in enumerate(items)}},
        "deviceKeyInfo": {"deviceKey": {
            1: 2, -1: 1, -2: p.x.to_bytes(32, "big"), -3: p.y.to_bytes(32, "big"),
        }},
        "validityInfo": {
            "signed": "2026-11-01T00:00:00Z", "validFrom": "2026-11-02T00:00:00Z",
            "validUntil": "2026-12-10T00:00:00Z",
        },
    }
    return _sign(signer, cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps(mso))), cert=leaf)


def _payload(transcript, namespaces, doc=DOC):
    # Construcción independiente del verificador.
    return cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps([
        "DeviceAuthentication",
        cbor2.loads(cbor2.loads(transcript).value),
        doc,
        cbor2.loads(namespaces),
    ])))


@pytest.fixture
def sample():
    root, leaf, signer = _make_chain()
    device = ec.generate_private_key(ec.SECP256R1())
    items = (_item(0, "sample_name", "TEST_PERSON"), _item(1, "sample_number", "TEST_001"))
    transcript = synthetic_transcript()
    namespaces = cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps({})))
    auth = _issuer(leaf, signer, items, device)
    signature = _sign(device, _payload(transcript, namespaces), detached=True)
    return dict(
        issuer_auth_bytes=auth, trusted_iaca_der=root, items=items, transcript_bytes=transcript,
        namespaces_bytes=namespaces, device_signature_bytes=signature, when=NOW,
    ), device


def _check(args, expected):
    report = precheck_synthetic_device_auth(**args)
    assert report["status"] == expected, report
    assert report["verified_identity"] is False
    assert report["device_auth_verified"] is False
    assert report["certificate_revocation_checked"] is False
    assert report["idc_verification_available"] is False
    assert "TEST_PERSON" not in json.dumps(report)
    assert "TEST_001" not in json.dumps(report)
    passed = expected == "synthetic_device_auth_precheck_passed_not_identity"
    assert report["synthetic_device_signature_valid"] is passed
    assert report["synthetic_session_binding_valid"] is passed
    return report


def test_valid_synthetic_device_signature(sample):
    args, _ = sample
    report = _check(args, "synthetic_device_auth_precheck_passed_not_identity")
    assert report["presented_item_digests_verified"] is True


def test_replay_on_fresh_transcript_rejected(sample):
    args, _ = sample
    args["transcript_bytes"] = synthetic_transcript()
    _check(args, "invalid_device_signature")


@pytest.mark.parametrize("mode", ["wrong_key", "wrong_doc", "altered_signature"])
def test_signature_not_bound_to_mso_or_session_rejected(sample, mode):
    args, device = sample
    if mode == "wrong_key":
        device = ec.generate_private_key(ec.SECP256R1())
    payload = _payload(
        args["transcript_bytes"], args["namespaces_bytes"],
        "org.example.other" if mode == "wrong_doc" else DOC,
    )
    raw = _sign(device, payload, detached=True)
    if mode == "altered_signature":
        fields = cbor2.loads(raw).value
        sig = bytes([fields[3][0] ^ 1]) + fields[3][1:]
        raw = cbor2.dumps(cbor2.CBORTag(18, [*fields[:3], sig]))
    args["device_signature_bytes"] = raw
    _check(args, "invalid_device_signature")


def test_attached_payload_rejected(sample):
    args, device = sample
    args["device_signature_bytes"] = _sign(
        device, _payload(args["transcript_bytes"], args["namespaces_bytes"])
    )
    _check(args, "invalid_detached_device_signature")


def test_nonempty_device_namespaces_rejected(sample):
    args, _ = sample
    args["namespaces_bytes"] = cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps({"unexpected": {}})))
    _check(args, "unexpected_device_namespaces")


def test_wrong_trust_root_rejected_before_device_signature(sample):
    args, _ = sample
    args["trusted_iaca_der"] = _make_chain()[0]
    _check(args, "invalid_certificate_chain")


def test_tampered_issuer_items_rejected_first(sample):
    args, _ = sample
    args["items"] = (_item(0, "sample_name", "TEST_PERSON", b"fedcba9876543210"), args["items"][1])
    _check(args, "digest_mismatch")


def test_malformed_transcript_rejected(sample):
    args, _ = sample
    args["transcript_bytes"] = cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps([None, None, None])))
    _check(args, "invalid_tag24")


def test_wrong_algorithm_rejected(sample):
    args, device = sample
    args["device_signature_bytes"] = _sign(
        device, _payload(args["transcript_bytes"], args["namespaces_bytes"]),
        header={1: -35}, detached=True,
    )
    _check(args, "unsupported_device_algorithm")
