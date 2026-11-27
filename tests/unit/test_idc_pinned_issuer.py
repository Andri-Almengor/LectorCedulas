"""QA24 uses synthetic certificate authorities only."""
import hashlib
from unittest.mock import Mock

import pytest

from tools.idc_diagnostic import photoid_candidate
from tools.idc_diagnostic.pinned_issuer import check_anchor, inspect_pinned_issuer
from test_idc_issuer_auth import NOW, _make_chain
from test_idc_issuer_consistency import _response


def _pin(der):
    return hashlib.sha256(der).hexdigest()


def test_matching_anchor():
    root, _, _ = _make_chain()
    assert check_anchor(root, _pin(root), when=NOW)


@pytest.mark.parametrize("mode", ["wrong_pin", "leaf", "bad_der", "missing"])
def test_invalid_anchor(mode):
    root, leaf, _ = _make_chain()
    der, pin = {
        "wrong_pin": (root, "0" * 64),
        "leaf": (leaf, _pin(leaf)),
        "bad_der": (b"bad", _pin(b"bad")),
        "missing": (None, None),
    }[mode]
    assert not check_anchor(der, pin, when=NOW)


def test_partial_chain_and_signature():
    response, root, _ = _response()
    result = inspect_pinned_issuer(response, root, _pin(root), when=NOW)
    assert all(result.values()), result


def test_wrong_ca_fails_chain():
    response, _, _ = _response()
    root, _, _ = _make_chain()
    result = inspect_pinned_issuer(response, root, _pin(root), when=NOW)
    assert result["mdl_pinned_anchor_precheck_passed"]
    assert not result["mdl_pinned_issuer_chain_precheck_passed"]
    assert not result["mdl_pinned_issuer_mso_precheck_passed"]


def test_bad_signature_fails():
    response, root, _ = _response()
    parts = response["documents"][0]["issuerSigned"]["issuerAuth"]
    parts[3] = bytes([parts[3][0] ^ 1]) + parts[3][1:]
    result = inspect_pinned_issuer(response, root, _pin(root), when=NOW)
    assert not result["mdl_pinned_issuer_signature_precheck_passed"]


def test_cli_rejects_incomplete_anchor_before_capture(monkeypatch, tmp_path):
    capture = Mock(side_effect=AssertionError("must not capture"))
    monkeypatch.setattr(photoid_candidate, "capture_serial", capture)
    with pytest.raises(SystemExit):
        photoid_candidate.main([
            "--port", "COM5", "--consent", "--allow-mdl-candidate",
            "--anchor-der", str(tmp_path / "root.der"),
        ])
    capture.assert_not_called()


def test_invalid_anchor_before_transport(monkeypatch):
    transport = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(photoid_candidate, "_get_transport_options", transport)
    result = photoid_candidate.probe_candidate(
        b"test", consent=True, allow_candidate=True, profile="mdl",
        anchor=(b"bad", _pin(b"bad")),
    )
    assert result["status"] == "invalid_or_unusable_pinned_anchor"
    assert not result["verified_identity"]
    transport.assert_not_called()
