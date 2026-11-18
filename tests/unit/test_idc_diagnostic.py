from __future__ import annotations

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
