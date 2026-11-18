from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

from tools.idc_diagnostic.__main__ import main
from tools.idc_diagnostic.bluetooth_probe import probe_bluetooth


def _runner(output: str, code: int = 0):
    def run(argv, **kwargs):
        assert argv[0] == "powershell.exe"
        assert kwargs["timeout"] == 8
        assert kwargs["capture_output"] is True
        return SimpleNamespace(stdout=output, returncode=code)
    return run


def test_detected_bluetooth_still_does_not_claim_ble_support():
    report = probe_bluetooth(system_name="Windows", runner=_runner("PRESENT\\n"))
    assert report["bluetooth_class_status"] == "detected"
    assert report["ble_session_supported"] == "not_tested"
    assert report["idc_verification_available"] is False
    assert "PRESENT" not in json.dumps(report)


def test_absent_bluetooth_keeps_official_manual_fallback():
    report = probe_bluetooth(system_name="Windows", runner=_runner("ABSENT"))
    assert report["bluetooth_class_status"] == "not_detected"
    assert report["no_bluetooth_fallback"] == "official_verifier_and_manual_registration"
    assert report["idc_verification_available"] is False


def test_probe_fails_closed_on_error_without_leaking_output():
    report = probe_bluetooth(
        system_name="Windows",
        runner=_runner("Device=SECRET MAC=11:22:33:44:55:66", code=1),
    )
    assert report["bluetooth_class_status"] == "unknown"
    assert "SECRET" not in json.dumps(report)


def test_probe_fails_closed_on_timeout():
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("powershell.exe", 8)
    report = probe_bluetooth(system_name="Windows", runner=timeout)
    assert report["bluetooth_class_status"] == "unknown"
    assert report["ble_session_supported"] == "not_tested"


def test_probe_non_windows_does_not_call_powershell():
    def forbidden(*args, **kwargs):
        raise AssertionError("PowerShell must not be invoked")
    report = probe_bluetooth(system_name="Linux", runner=forbidden)
    assert report["bluetooth_class_status"] == "not_applicable"


def test_cli_probe_emits_no_device_identifiers(monkeypatch, capsys):
    monkeypatch.setattr(
        "tools.idc_diagnostic.__main__.probe_bluetooth",
        lambda: probe_bluetooth(system_name="Windows", runner=_runner("PRESENT")),
    )
    assert main(["--bluetooth-check"]) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["bluetooth_class_status"] == "detected"
    assert report["idc_verification_available"] is False
