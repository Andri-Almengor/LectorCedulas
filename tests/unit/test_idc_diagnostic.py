from __future__ import annotations

import base64
import json

from tools.idc_diagnostic.__main__ import main
from tools.idc_diagnostic.inspect import MAX_SCAN_BYTES, inspect_qr


def test_mdoc_candidate_does_not_claim_verification():
    result = inspect_qr(b"mdoc:gwECAw\r\n")
    assert result["classification"] == "mdoc_candidate"
    assert result["base64url_valid"] is True
    assert result["decoded_bytes"] == 4
    assert result["cbor_initial_major_type"] == "array"
    assert result["verified_identity"] is False
    assert "gwECAw" not in json.dumps(result)


def test_invalid_mdoc_data_is_not_accepted():
    result = inspect_qr(b"mdoc:invalid***")
    assert result["base64url_valid"] is False
    assert result["verified_identity"] is False


def test_url_report_never_exposes_personal_values():
    secret = "https://www.consulta.tse.go.cr/consultacedula/Cedula?cedula=119320121&token=secret"
    report = json.dumps(inspect_qr(secret.encode()))
    assert "119320121" not in report
    assert "secret" not in report
    assert '"url_qr"' in report


def test_large_scan_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        inspect_qr(b"X" * (MAX_SCAN_BYTES + 1))


def test_cli_file_only_prints_sanitized_metadata(tmp_path, capsys):
    sample = tmp_path / "sample.txt"
    sample.write_text("mdoc:gwECAw", encoding="utf-8")
    output = tmp_path / "metadata.json"
    assert main(["--sample-file", str(sample), "--output", str(output)]) == 0
    content = output.read_text(encoding="utf-8")
    assert "gwECAw" not in content
    assert json.loads(content)["classification"] == "mdoc_candidate"
    assert "gwECAw" not in capsys.readouterr().out


def test_cli_never_overwrites_existing_report(tmp_path, capsys):
    sample = tmp_path / "sample.txt"
    sample.write_text("mdoc:gwECAw", encoding="utf-8")
    output = tmp_path / "metadata.json"
    output.write_text("previous", encoding="utf-8")
    assert main(["--sample-file", str(sample), "--output", str(output)]) == 1
    assert output.read_text(encoding="utf-8") == "previous"
    capsys.readouterr()


def _synthetic_mdoc(raw_cbor: bytes) -> bytes:
    return b"mdoc:" + base64.urlsafe_b64encode(raw_cbor).rstrip(b"=")


def test_iso_23220_map_shape_discovers_ble_without_leaking_data():
    # mapa: {0: "1.0", 1: [1, b"\\x00"], 2: [[2, 1, {0: true, 1: false}]]}
    synthetic = bytes.fromhex("a30063312e3001820141000281830201a200f501f4")
    report = inspect_qr(_synthetic_mdoc(synthetic))
    assert report["cbor_initial_major_type"] == "map"
    assert report["cbor_structure_decoded"] is True
    assert report["cbor_root_items"] == 3
    assert report["known_engagement_fields_present"] == [0, 1, 2]
    assert report["cbor_profile_hint"] == "iso_23220_map_shape_candidate"
    assert report["transport_candidates"] == ["BLE"]
    assert report["verified_identity"] is False
    assert "312e30" not in json.dumps(report)


def test_iso_18013_array_shape_is_supported_as_candidate():
    # [ "1.0", [1, h'00'], [[2, 1, {}]] ]
    synthetic = bytes.fromhex("8363312e308201410081830201a0")
    report = inspect_qr(_synthetic_mdoc(synthetic))
    assert report["cbor_structure_decoded"] is True
    assert report["cbor_profile_hint"] == "iso_18013_array_shape_candidate"
    assert report["transport_candidates"] == ["BLE"]


def test_truncated_cbor_never_claims_valid_structure():
    report = inspect_qr(_synthetic_mdoc(b"\\xa1\\x00"))
    assert report["base64url_valid"] is True
    assert report["cbor_structure_decoded"] is False
    assert report["verified_identity"] is False


def test_unknown_cbor_map_cannot_claim_ble_by_searching_text():
    # { "BLE": "not evidence of a transport" }
    synthetic = bytes.fromhex("a163424c45781b6e6f742065766964656e6365206f662061207472616e73706f7274")
    report = inspect_qr(_synthetic_mdoc(synthetic))
    assert report["cbor_profile_hint"] == "unidentified"
    assert report["transport_candidates"] == []
    assert "not evidence" not in json.dumps(report)


def test_structural_traversal_is_bounded():
    nested = (b"\\x81" * 15) + b"\\x01"
    report = inspect_qr(_synthetic_mdoc(nested))
    assert report["cbor_structure_decoded"] is False
    assert report["verified_identity"] is False


def test_four_field_map_announces_ble_and_nfc_without_identity_verification():
    # Muestra SINTÉTICA: {0: "1.0", 1: [1, h'00'],
    # 2: [[2, 1, {}], [1, 1, {}]], 3: []}; no contiene datos reales.
    synthetic = bytes.fromhex("a40063312e3001820141000282830201a0830101a00380")
    raw = _synthetic_mdoc(synthetic)
    result = inspect_qr(raw)
    assert result["classification"] == "mdoc_candidate"
    assert result["cbor_structure_decoded"] is True
    assert result["cbor_root_items"] == 4
    assert result["known_engagement_fields_present"] == [0, 1, 2, 3]
    assert result["cbor_profile_hint"] == "iso_23220_map_shape_candidate"
    assert result["transport_candidates"] == ["BLE", "NFC"]
    assert result["verified_identity"] is False
    assert "mdoc:" not in json.dumps(result)
