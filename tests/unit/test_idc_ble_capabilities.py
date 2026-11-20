"""Pruebas del diagnóstico opcional WinRT sin usar adaptadores reales."""
from __future__ import annotations

import json

from tools.idc_diagnostic.__main__ import main
from tools.idc_diagnostic.ble_capabilities import probe_ble_capabilities


async def _good_adapter():
    return {
        "low_energy_supported": True,
        "central_role_supported": True,
        "peripheral_role_supported": False,
    }


async def _no_adapter():
    return None


async def _missing_winrt():
    raise ModuleNotFoundError("No module named winrt")


async def _winrt_error():
    raise RuntimeError("Do not expose local device identifiers")


async def _bad_adapter():
    return {
        "low_energy_supported": "True",
        "central_role_supported": True,
        "peripheral_role_supported": False,
    }


def test_real_capabilities_are_not_cryptographic_verification():
    report = probe_ble_capabilities(system_name="Windows", adapter_reader=_good_adapter)
    assert report["adapter_status"] == "detected"
    assert report["low_energy_supported"] is True
    assert report["central_role_supported"] is True
    assert report["peripheral_role_supported"] is False
    assert report["nearby_device_scan_performed"] is False
    assert report["gatt_connection_tested"] is False
    assert report["verified_identity"] is False
    assert report["idc_verification_available"] is False


def test_no_default_adapter_is_not_confused_with_missing_dependency():
    report = probe_ble_capabilities(system_name="Windows", adapter_reader=_no_adapter)
    assert report["adapter_status"] == "no_default_adapter"
    assert report["low_energy_supported"] is None


def test_missing_winrt_does_not_break_diagnostic():
    report = probe_ble_capabilities(system_name="Windows", adapter_reader=_missing_winrt)
    assert report["adapter_status"] == "winrt_dependency_missing"
    assert report["verified_identity"] is False


def test_errors_do_not_leak_device_information():
    report = probe_ble_capabilities(system_name="Windows", adapter_reader=_winrt_error)
    assert report["adapter_status"] == "api_error"
    assert "identifiers" not in json.dumps(report)


def test_wrong_api_types_are_not_truthy():
    report = probe_ble_capabilities(system_name="Windows", adapter_reader=_bad_adapter)
    assert report["adapter_status"] == "api_error"
    assert report["low_energy_supported"] is None


def test_non_windows_never_calls_winrt():
    report = probe_ble_capabilities(system_name="Linux", adapter_reader=_winrt_error)
    assert report["adapter_status"] == "not_applicable"
    assert report["verified_identity"] is False


def test_cli_ble_capabilities_outputs_only_sanitized_metadata(monkeypatch, capsys):
    monkeypatch.setattr(
        "tools.idc_diagnostic.__main__.probe_ble_capabilities",
        lambda: probe_ble_capabilities(system_name="Windows", adapter_reader=_good_adapter),
    )
    assert main(["--ble-capabilities"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["adapter_status"] == "detected"
    assert report["gatt_connection_tested"] is False
