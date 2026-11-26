"""Pruebas de errores de DLL bloqueada, sin afectar políticas de Windows."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.idc_diagnostic.ble_runtime import (
    classify_ble_import_error,
    probe_ble_runtime,
)
from tools.idc_diagnostic.ble_observer import observe_mdoc_ble_advertising


@pytest.mark.parametrize(
    "error,status",
    [
        (
            ImportError("DLL load failed importing _winrt: Una directiva de Control "
                        "de aplicaciones bloqueó este archivo."),
            "windows_application_control_blocked",
        ),
        (
            ImportError("DLL load failed importing _winrt: "
                        "An Application Control policy has blocked this file."),
            "windows_application_control_blocked",
        ),
        (ModuleNotFoundError("No module named 'winrt'"), "ble_dependency_missing"),
        (ImportError("DLL load failed: specified module could not be found"),
         "ble_native_extension_load_error"),
    ],
)
def test_classifies_import_failure_without_leaking_error_details(error, status):
    assert classify_ble_import_error(error) == status


def test_runtime_preflight_identifies_policy_block_without_scan():
    def blocked():
        raise ImportError("winrt._winrt: Una directiva de Control de aplicaciones "
                          "bloqueó este archivo, MAC AA:BB:CC:DD:EE:FF")

    report = probe_ble_runtime(load=blocked)
    assert report["status"] == "windows_application_control_blocked"
    assert report["ble_runtime_imported"] is False
    assert report["bluetooth_scan_performed"] is False
    assert report["verified_identity"] is False
    assert "AA:BB" not in json.dumps(report)


def test_runtime_preflight_success_is_not_identity_verification():
    report = probe_ble_runtime(load=lambda: None)
    assert report["status"] == "ble_runtime_import_ok"
    assert report["ble_runtime_imported"] is True
    assert report["bluetooth_scan_performed"] is False
    assert report["idc_verification_available"] is False


def test_runtime_preflight_runs_without_site_packages():
    root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, "-S", "-m", "tools.idc_diagnostic", "--ble-runtime-check"],
        cwd=root, capture_output=True, text=True, timeout=15, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "ble_dependency_missing"
    assert result["verified_identity"] is False


def test_ble_observer_reports_policy_block_as_distinct_from_missing_dependency():
    async def simulate_policy(_uuid, _seconds):
        raise ImportError("Una directiva de Control de aplicaciones bloqueó este archivo")

    def fake_cbor(_bytes):
        return {
            0: "1.0",
            2: [[2, 1, {
                0: True, 1: False,
                10: bytes.fromhex("6fa459a16bd5486b8b591c375ee613d1"),
            }]],
        }

    import base64
    sample = b"mdoc:" + base64.urlsafe_b64encode(b"synthetic-cbor").rstrip(b"=")
    result = observe_mdoc_ble_advertising(
        sample, consent=True, nearby_scan_ok=True, duration_seconds=3,
        decode_cbor=fake_cbor, observe=simulate_policy,
    )
    assert result["status"] == "windows_application_control_blocked"
    assert result["any_ble_advertisements_seen"] is False
    assert result["verified_identity"] is False


def test_cli_ble_runtime_check_never_requests_qr(monkeypatch, capsys):
    from tools.idc_diagnostic.__main__ import main

    def forbids_scanning(*_args, **_kwargs):
        raise AssertionError("This must never open a serial or BLE scanner")

    monkeypatch.setattr("tools.idc_diagnostic.__main__.capture_serial", forbids_scanning)
    monkeypatch.setattr("tools.idc_diagnostic.__main__.probe_ble_runtime",
                        lambda: probe_ble_runtime(load=lambda: None))
    assert main(["--ble-runtime-check"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ble_runtime_import_ok"
    assert report["bluetooth_scan_performed"] is False
