"""QA13: pruebas exclusivamente con credenciales y valores ficticios."""
import hashlib
import json

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from tools.idc_diagnostic.signed_items_lab import DOC, NAMESPACE, precheck_synthetic_signed_items
from test_idc_issuer_auth import NOW, _make_chain


def _item(digest_id, name, value, salt=b"0123456789abcdef"):
    return cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps({
        "digestID": digest_id, "random": salt, "elementIdentifier": name, "elementValue": value,
    })))


def _sign(leaf, key, items, *, algorithm="SHA-256", namespace=NAMESPACE, doc=DOC):
    mso = {
        "version": "1.0", "digestAlgorithm": algorithm, "docType": doc,
        "valueDigests": {namespace: {i: hashlib.sha256(item).digest() for i, item in enumerate(items)}},
        "validityInfo": {
            "signed": "2026-11-01T00:00:00Z",
            "validFrom": "2026-11-02T00:00:00Z",
            "validUntil": "2026-12-10T00:00:00Z",
        },
    }
    protected = cbor2.dumps({1: -7})
    payload = cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps(mso)))
    der = key.sign(cbor2.dumps(["Signature1", protected, b"", payload]), ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    return cbor2.dumps(cbor2.CBORTag(
        18, [protected, {33: [leaf]}, payload, r.to_bytes(32, "big") + s.to_bytes(32, "big")]
    ))


@pytest.fixture
def sample():
    root, leaf, key = _make_chain()
    items = (_item(0, "sample_name", "TEST_PERSON"), _item(1, "sample_number", "TEST_001"))
    return root, leaf, key, items


def _check(root, auth, items):
    result = precheck_synthetic_signed_items(auth, trusted_iaca_der=root, items=items, when=NOW)
    assert result["verified_identity"] is False
    assert result["device_auth_verified"] is False
    assert result["idc_verification_available"] is False
    assert "TEST_PERSON" not in json.dumps(result)
    assert "TEST_001" not in json.dumps(result)
    return result


def test_matching_signature_and_presented_digests(sample):
    root, leaf, key, items = sample
    result = _check(root, _sign(leaf, key, items), items)
    assert result["status"] == "synthetic_signed_items_precheck_passed_not_identity", result
    assert result["issuer_auth_precheck_passed"] is True, result
    assert result["presented_item_digests_verified"] is True, result


@pytest.mark.parametrize("case", ["tampered", "missing", "duplicate", "trailing", "unknown"])
def test_bad_items_fail_closed(sample, case):
    root, leaf, key, items = sample
    auth = _sign(leaf, key, items)
    other = {
        "tampered": (_item(0, "sample_name", "TEST_PERSON", b"fedcba9876543210"), items[1]),
        "missing": items[:1],
        "duplicate": (items[0], items[0]),
        "trailing": (items[0] + b"\x00", items[1]),
        "unknown": (_item(5, "sample_name", "TEST_PERSON"), items[1]),
    }[case]
    result = _check(root, auth, other)
    assert result["issuer_auth_precheck_passed"] is True, result
    assert result["presented_item_digests_verified"] is False
    expected = {
        "tampered": "digest_mismatch", "missing": "missing_or_extra_items",
        "duplicate": "duplicate_item", "trailing": "trailing_cbor_data",
        "unknown": "unknown_digest_id",
    }
    assert result["status"] == expected[case], result


@pytest.mark.parametrize("kwargs", [
    {"algorithm": "SHA-512"}, {"namespace": "org.example.other"}, {"doc": "org.example.other"},
])
def test_unsupported_profile_rejected(sample, kwargs):
    root, leaf, key, items = sample
    assert _check(root, _sign(leaf, key, items, **kwargs), items)["presented_item_digests_verified"] is False


def test_missing_or_wrong_root(sample):
    _, leaf, key, items = sample
    auth = _sign(leaf, key, items)
    wrong_root, _, _ = _make_chain()
    for root in (None, wrong_root):
        result = _check(root, auth, items)
        assert result["issuer_auth_precheck_passed"] is False
        assert result["presented_item_digests_verified"] is False


def test_corrupted_signature(sample):
    root, leaf, key, items = sample
    fields = cbor2.loads(_sign(leaf, key, items)).value
    signature = bytes([fields[3][0] ^ 1]) + fields[3][1:]
    auth = cbor2.dumps(cbor2.CBORTag(18, [*fields[:3], signature]))
    assert _check(root, auth, items)["presented_item_digests_verified"] is False


def test_duplicate_cbor_keys_rejected_even_if_signed(sample):
    root, leaf, key, items = sample
    # Map de cinco pares con digestID duplicado.
    decoded = cbor2.loads(cbor2.loads(items[0]).value)
    encoded = cbor2.dumps(decoded)
    duplicated = b"\xa5" + encoded[1:] + cbor2.dumps("digestID") + cbor2.dumps(0)
    bad_items = (cbor2.dumps(cbor2.CBORTag(24, duplicated)), items[1])
    assert _check(root, _sign(leaf, key, bad_items), bad_items)["presented_item_digests_verified"] is False
