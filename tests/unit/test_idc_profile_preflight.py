"""Pruebas del CLI QA16 con archivos temporales exclusivamente sintéticos."""
import hashlib
import json

from tools.idc_diagnostic.profile_preflight import run
from test_idc_issuer_auth import _make_chain
from test_idc_profile_readiness import _profile


def _report(capsys):
    result = json.loads(capsys.readouterr().out)
    assert result["verified_identity"] is False
    assert result["iaca_trust_anchor_validated"] is False
    assert result["idc_verification_available"] is False
    return result


def test_no_material(capsys):
    assert run([]) == 2
    assert _report(capsys)["status"] == "profile_required"


def test_missing_file_is_sanitized(tmp_path, capsys):
    assert run(["--profile", str(tmp_path / "private-name.json")]) == 2
    result = _report(capsys)
    assert result["status"] == "local_material_unreadable_or_invalid"
    assert "private-name" not in json.dumps(result)


def test_oversize_profile(tmp_path, capsys):
    p = tmp_path / "profile.json"
    p.write_bytes(b"x" * 8193)
    assert run(["--profile", str(p)]) == 2
    assert _report(capsys)["status"] == "local_material_unreadable_or_invalid"


def test_profile_and_anchor_need_independent_pin(tmp_path, capsys):
    p = tmp_path / "profile.json"
    p.write_bytes(_profile(reader_auth="not_required"))
    a = tmp_path / "anchor.der"
    a.write_bytes(_make_chain()[0])
    assert run(["--profile", str(p), "--anchor-der", str(a)]) == 2
    assert _report(capsys)["status"] == "independent_anchor_pin_required"


def test_candidate_ready_not_verified(tmp_path, capsys):
    root = _make_chain()[0]
    p = tmp_path / "profile.json"
    p.write_bytes(_profile(reader_auth="not_required"))
    a = tmp_path / "anchor.der"
    a.write_bytes(root)
    h = tmp_path / "pin.txt"
    pin = hashlib.sha256(root).hexdigest()
    h.write_text(pin.upper() + "\n", encoding="ascii")
    assert run(["--profile", str(p), "--anchor-der", str(a), "--anchor-pin-file", str(h)]) == 0
    report = _report(capsys)
    assert report["status"] == "candidate_profile_structurally_ready_not_verified"
    assert pin not in json.dumps(report)
    assert "lab.invalid" not in json.dumps(report)


def test_wrong_pin(tmp_path, capsys):
    p = tmp_path / "profile.json"
    p.write_bytes(_profile(reader_auth="not_required"))
    a = tmp_path / "anchor.der"
    a.write_bytes(_make_chain()[0])
    h = tmp_path / "pin.txt"
    h.write_text("0" * 64, encoding="ascii")
    assert run(["--profile", str(p), "--anchor-der", str(a), "--anchor-pin-file", str(h)]) == 2
    assert _report(capsys)["status"] == "anchor_fingerprint_mismatch"
