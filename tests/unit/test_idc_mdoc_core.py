"""Pruebas ISO/IEC 18013-5 con claves efímeras totalmente SINTÉTICAS."""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import cbor2
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from tools.idc_diagnostic.mdoc_core import (
    MdocProtocolError,
    build_device_request,
    prepare_reader_session,
    preflight_mdoc_crypto,
)


def _qr(*, root_style="map", key_override=None, cipher_suite=1):
    device = ec.generate_private_key(ec.SECP256R1())
    public = device.public_key().public_numbers()
    cose = {
        1: 2, -1: 1,
        -2: public.x.to_bytes(32, "big"),
        -3: public.y.to_bytes(32, "big"),
    }
    encoded = cbor2.dumps(cose if key_override is None else key_override)
    security = [cipher_suite, cbor2.CBORTag(24, encoded)]
    methods = [[2, 1, {0: True, 1: False, 10: bytes.fromhex("6fa459a16bd5486b8b591c375ee613d1")}]]
    if root_style == "map":
        engagement = {0: "1.0", 1: security, 2: methods, 3: []}
    else:
        engagement = ["1.0", security, methods]
    raw = cbor2.dumps(engagement)
    return b"mdoc:" + base64.urlsafe_b64encode(raw).rstrip(b"=")


@pytest.mark.parametrize("style", ["map", "array"])
def test_prepare_reader_session_uses_p256_ecdh_hkdf_and_tag24(style):
    scan = _qr(root_style=style)
    one = prepare_reader_session(scan)
    two = prepare_reader_session(scan)

    assert len(one.sk_reader) == len(one.sk_device) == 32
    assert one.sk_reader != one.sk_device
    assert one.sk_reader != two.sk_reader
    assert one.sk_device != two.sk_device
    assert "secret material redacted" in repr(one)
    assert one.engagement_profile == (
        "map_extension_candidate" if style == "map" else "iso_18013_array_candidate"
    )
    encoded_transcript = cbor2.loads(one.session_transcript)
    assert isinstance(encoded_transcript, cbor2.CBORTag)
    assert encoded_transcript.tag == 24
    transcript = cbor2.loads(encoded_transcript.value)
    assert len(transcript) == 3
    assert transcript[2] is None
    assert isinstance(transcript[0], cbor2.CBORTag)
    assert transcript[0].tag == 24
    assert isinstance(transcript[1], cbor2.CBORTag)
    assert transcript[1].tag == 24
    assert cbor2.loads(transcript[1].value) == cbor2.loads(one.reader_cose_key)


def test_preflight_returns_only_metadata():
    qr = _qr()
    report = preflight_mdoc_crypto(qr, consent=True)
    assert report["status"] == "local_crypto_preflight_passed_not_verified"
    assert report["session_keys_derived_locally"] is True
    assert report["ble_link_established"] is False
    assert report["mdoc_session_established"] is False
    assert report["issuer_signature_verified"] is False
    assert report["device_auth_verified"] is False
    assert report["iaca_trust_anchor_validated"] is False
    assert report["verified_identity"] is False
    assert b"mdoc:" not in json.dumps(report).encode()


def test_explicit_consent_required_before_crypto():
    report = preflight_mdoc_crypto(_qr(), consent=False)
    assert report["status"] == "consent_required"
    assert report["session_keys_derived_locally"] is False


def test_invalid_p256_coordinates_are_rejected_without_sensitive_data():
    qr = _qr(key_override={1: 2, -1: 1, -2: b"\xff" * 32, -3: b"\xff" * 32})
    report = preflight_mdoc_crypto(qr, consent=True)
    assert report["status"] == "invalid_p256_point"
    assert "ffff" not in json.dumps(report)
    assert report["verified_identity"] is False


def test_unsupported_cipher_suite_is_rejected():
    report = preflight_mdoc_crypto(_qr(cipher_suite=99), consent=True)
    assert report["status"] == "unsupported_cipher_suite"
    assert report["session_keys_derived_locally"] is False


def test_trailing_data_rejected():
    qr = _qr()
    raw = base64.urlsafe_b64decode(qr[5:] + b"=" * (-len(qr[5:]) % 4))
    qr_bad = b"mdoc:" + base64.urlsafe_b64encode(raw + b"\x00").rstrip(b"=")
    report = preflight_mdoc_crypto(qr_bad, consent=True)
    assert report["status"] == "invalid_cbor"


def test_device_request_has_explicit_schema_no_retention():
    encoded = build_device_request(
        doc_type="org.example.photoid",
        requested_namespaces={"org.example.person": ("family_name", "given_name")},
    )
    request = cbor2.loads(encoded)
    assert request["version"] == "1.0"
    assert len(request["docRequests"]) == 1
    item = request["docRequests"][0]["itemsRequest"]
    assert isinstance(item, cbor2.CBORTag) and item.tag == 24
    inner = cbor2.loads(item.value)
    assert inner["docType"] == "org.example.photoid"
    assert inner["nameSpaces"]["org.example.person"] == {
        "family_name": False, "given_name": False
    }
    assert "readerAuth" not in request["docRequests"][0]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"doc_type": "", "requested_namespaces": {"x": ("name",)}},
        {"doc_type": "org.example", "requested_namespaces": {}},
        {"doc_type": "org.example", "requested_namespaces": {"x": ("name", "name")}},
        {"doc_type": "org.example", "requested_namespaces": {"x": tuple()}},
        {"doc_type": "org.example", "requested_namespaces": {"x": ("bad\x00",)}},
    ],
)
def test_request_rejects_bad_or_nonminimal_selection(kwargs):
    with pytest.raises(MdocProtocolError):
        build_device_request(**kwargs)


def test_cli_real_scan_report_never_exposes_qr(monkeypatch, capsys):
    from tools.idc_diagnostic.__main__ import main

    qr = _qr()
    monkeypatch.setattr(
        "tools.idc_diagnostic.__main__.capture_serial",
        lambda port, baudrate, timeout_seconds: qr,
    )
    assert main(["--mdoc-preflight", "--port", "COM9", "--consent"]) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["status"] == "local_crypto_preflight_passed_not_verified"
    assert report["verified_identity"] is False
    assert qr.decode() not in output
    assert "sk_reader" not in output
    assert "session_transcript" not in output


def test_cli_requires_explicit_consent():
    from tools.idc_diagnostic.__main__ import main

    with pytest.raises(SystemExit):
        main(["--mdoc-preflight", "--port", "COM9"])


def test_core_still_imports_without_crypto_extras():
    root = Path(__file__).resolve().parents[2]
    p = subprocess.run(
        [
            sys.executable, "-S", "-c",
            "import tools.idc_diagnostic.mdoc_core as m; "
            "assert m.MdocProtocolError.__name__ == 'MdocProtocolError'; "
            "print('optional imports deferred')",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip() == "optional imports deferred"
