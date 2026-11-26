"""Observación BLE sin guardar identificadores ni conectar con dispositivos reales."""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from types import SimpleNamespace
from uuid import UUID

import pytest

from tools.idc_diagnostic.ble_observer import (
    _observe_advertisements,
    observe_mdoc_ble_advertising,
)

TEST_UUID = UUID("6fa459a1-6bd5-486b-8b59-1c375ee613d1")


def _qr() -> bytes:
    return b"mdoc:" + base64.urlsafe_b64encode(b"synthetic-only").rstrip(b"=")


def _root(_raw: bytes):
    return {0: "1.0", 2: [[2, 1, {0: True, 1: False, 10: TEST_UUID.bytes}]]}


async def _any_devices(_uuid: UUID, _seconds: float):
    return {
        "any_ble_advertisements_seen": True,
        "qr_service_uuid_advertised": False,
        "qr_uuid_in_service_data": False,
    }


async def _target(_uuid: UUID, _seconds: float):
    return {
        "any_ble_advertisements_seen": True,
        "qr_service_uuid_advertised": True,
        "qr_uuid_in_service_data": False,
    }


async def _no_devices(_uuid: UUID, _seconds: float):
    return {
        "any_ble_advertisements_seen": False,
        "qr_service_uuid_advertised": False,
        "qr_uuid_in_service_data": False,
    }


async def _failed(_uuid: UUID, _seconds: float):
    raise RuntimeError("Nearby phone Bluetooth address 01:02:03:04:05:06")


def test_requires_two_explicit_permissions_and_does_not_scan():
    called = False

    async def sentinel(_uuid, _duration):
        nonlocal called
        called = True
        return await _target(_uuid, _duration)

    report = observe_mdoc_ble_advertising(
        _qr(), consent=True, nearby_scan_ok=False, decode_cbor=_root, observe=sentinel,
    )
    assert report["status"] == "consent_required"
    assert called is False
    assert report["verified_identity"] is False
    assert report["ble_link_established"] is False


@pytest.mark.parametrize(
    "observe,status",
    [
        (_any_devices, "other_advertisements_seen_not_target"),
        (_target, "target_service_advertised"),
        (_no_devices, "no_ble_advertisements_received"),
        (_failed, "ble_scan_error"),
    ],
)
def test_aggregate_statuses_without_device_information(observe, status):
    report = observe_mdoc_ble_advertising(
        _qr(), consent=True, nearby_scan_ok=True, decode_cbor=_root, observe=observe,
        duration_seconds=3,
    )
    assert report["status"] == status
    assert report["verified_identity"] is False
    assert report["mdoc_session_established"] is False
    assert report["gatt_link_tested"] is False
    assert str(TEST_UUID) not in json.dumps(report)
    assert "01:02:03" not in json.dumps(report)


def test_bad_duration_is_not_scanned():
    report = observe_mdoc_ble_advertising(
        _qr(), consent=True, nearby_scan_ok=True, decode_cbor=_root,
        duration_seconds=100, observe=_target,
    )
    assert report["status"] == "invalid_scan_duration"


def test_scanner_uses_no_uuid_filter_and_retains_no_identifiers(monkeypatch):
    observed = {"scanner_filter": "unvisited"}
    adverts = [
        SimpleNamespace(service_uuids=["0000180a-0000-1000-8000-00805f9b34fb"], service_data={}),
        SimpleNamespace(service_uuids=[str(TEST_UUID)], service_data={}),
    ]

    class FakeScanner:
        def __init__(self, detection_callback, scanning_mode):
            observed["scanner_filter"] = None
            observed["scanning_mode"] = scanning_mode
            self.callback = detection_callback

        async def __aenter__(self):
            for advert in adverts:
                self.callback(SimpleNamespace(name="nearby-secret-name", address="AA:BB:CC:DD:EE:FF"), advert)
            return self

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setitem(sys.modules, "bleak", SimpleNamespace(BleakScanner=FakeScanner))
    result = asyncio.run(_observe_advertisements(TEST_UUID, 0))
    assert result == {
        "any_ble_advertisements_seen": True,
        "qr_service_uuid_advertised": True,
        "qr_uuid_in_service_data": False,
    }
    assert observed == {"scanner_filter": None, "scanning_mode": "active"}
    assert "nearby-secret-name" not in json.dumps(result)


def test_uuid_only_in_service_data_detected(monkeypatch):
    class Scanner:
        def __init__(self, detection_callback, scanning_mode):
            self.callback = detection_callback

        async def __aenter__(self):
            self.callback(
                object(),
                SimpleNamespace(service_uuids=[], service_data={str(TEST_UUID): b"secret"}),
            )
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setitem(sys.modules, "bleak", SimpleNamespace(BleakScanner=Scanner))
    result = asyncio.run(_observe_advertisements(TEST_UUID, 0))
    assert result["any_ble_advertisements_seen"] is True
    assert result["qr_uuid_in_service_data"] is True
    assert "secret" not in json.dumps(result)


def test_cli_requires_opt_in_before_com_port_is_opened(monkeypatch):
    from tools.idc_diagnostic.__main__ import main

    def forbidden(**kwargs):
        raise AssertionError("COM port must stay closed without extra opt-in")

    monkeypatch.setattr("tools.idc_diagnostic.__main__.capture_serial", forbidden)
    with pytest.raises(SystemExit):
        main(["--ble-observe-check", "--port", "COM5", "--consent"])


def test_cli_emits_only_metadata_and_uses_correct_port(monkeypatch, capsys):
    from tools.idc_diagnostic.__main__ import main

    seen = {}

    def capture(port, baudrate, timeout_seconds):
        seen["port"] = port
        return _qr()

    def inspect(raw, *, consent, nearby_scan_ok, duration_seconds):
        assert raw == _qr()
        assert consent and nearby_scan_ok
        seen["duration"] = duration_seconds
        return {"status": "no_ble_advertisements_received", "verified_identity": False}

    monkeypatch.setattr("tools.idc_diagnostic.__main__.capture_serial", capture)
    monkeypatch.setattr("tools.idc_diagnostic.__main__.observe_mdoc_ble_advertising", inspect)
    assert main([
        "--ble-observe-check", "--port", "COM5", "--consent", "--nearby-scan-ok",
        "--ble-scan-seconds", "20",
    ]) == 0
    output = capsys.readouterr().out
    assert seen == {"port": "COM5", "duration": 20.0}
    assert "synthetic-only" not in output
    assert '"verified_identity": false' in output
