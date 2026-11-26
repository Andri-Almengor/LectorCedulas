"""Prueba de descubrimiento de GATT con QR/objetos de dispositivo sintéticos."""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from types import SimpleNamespace
from uuid import UUID

import pytest

from tools.idc_diagnostic.ble_gatt_probe import (
    _discover_gatt,
    probe_mdoc_ble_gatt,
)
from tools.idc_diagnostic.gatt_codec import (
    STATE_UUID,
    CLIENT_TO_SERVER_UUID,
    SERVER_TO_CLIENT_UUID,
)

UUID_TEST = UUID("6fa459a1-6bd5-486b-8b59-1c375ee613d1")


def _raw():
    return b"mdoc:" + base64.urlsafe_b64encode(b"synthetic-bytes").rstrip(b"=")


def _engagement(_raw_bytes):
    return {0: "1.0", 2: [[2, 1, {0: True, 1: False, 10: UUID_TEST.bytes}]]}


def _good():
    return {
        "device_found": True,
        "ble_connected": True,
        "gatt_service_found": True,
        "state_characteristic_found": True,
        "client_to_server_characteristic_found": True,
        "server_to_client_characteristic_found": True,
        "state_supports_notify": True,
        "state_supports_write": True,
        "client_to_server_supports_write": True,
        "server_to_client_supports_notify": True,
    }


async def _success(uuid, window):
    assert uuid == UUID_TEST
    assert window >= 3
    return _good()


async def _no_uuid(_uuid, _window):
    return {"device_found": False}


async def _not_connected(_uuid, _window):
    return {"device_found": True, "ble_connected": False}


async def _no_service(_uuid, _window):
    return {"device_found": True, "ble_connected": True, "gatt_service_found": False}


async def _bad_chars(_uuid, _window):
    result = _good()
    result["server_to_client_supports_notify"] = False
    return result


def test_ready_gatt_is_not_verified_mdoc_session():
    result = probe_mdoc_ble_gatt(_raw(), consent=True, decode_cbor=_engagement, discover=_success)
    assert result["status"] == "gatt_profile_discovered_not_session_started"
    assert result["gatt_service_found"] is True
    assert result["gatt_characteristics_inspected"] is True
    assert result["gatt_link_tested"] is True
    assert result["gatt_profile_properties_match"] is True
    assert result["gatt_values_read"] is False
    assert result["gatt_writes_performed"] is False
    assert result["gatt_notifications_subscribed"] is False
    assert result["mdoc_session_established"] is False
    assert result["verified_identity"] is False
    assert str(UUID_TEST) not in json.dumps(result)


@pytest.mark.parametrize("func,status", [
    (_no_uuid, "service_not_found"),
    (_not_connected, "connection_not_established"),
    (_no_service, "gatt_service_missing_after_connection"),
    (_bad_chars, "gatt_profile_incomplete_or_different"),
])
def test_gatt_fails_closed(func, status):
    result = probe_mdoc_ble_gatt(_raw(), consent=True, decode_cbor=_engagement, discover=func)
    assert result["status"] == status
    assert result["verified_identity"] is False
    if status in ("service_not_found", "connection_not_established"):
        assert result["gatt_link_tested"] is False


def test_consent_required_before_parse_or_scan():
    called = False

    def forbidden(_raw_bytes):
        nonlocal called
        called = True
        raise RuntimeError("Unexpected parsing")

    result = probe_mdoc_ble_gatt(_raw(), consent=False, decode_cbor=forbidden, discover=_success)
    assert result["status"] == "consent_required"
    assert called is False


def test_invalid_timeout_rejects_before_scan():
    report = probe_mdoc_ble_gatt(_raw(), consent=True, timeout_seconds=90, decode_cbor=_engagement, discover=_success)
    assert report["status"] == "invalid_timeout"
    assert report["ble_link_established"] is False


def test_native_gatt_uses_targeted_scan_and_only_inspects_characteristics(monkeypatch):
    info = {"filter": None, "disconnected": False, "connected": False}
    characteristic_list = [
        SimpleNamespace(uuid=STATE_UUID, properties=["notify", "write"]),
        SimpleNamespace(uuid=CLIENT_TO_SERVER_UUID, properties=["write-without-response"]),
        SimpleNamespace(uuid=SERVER_TO_CLIENT_UUID, properties=["notify"]),
        SimpleNamespace(uuid="a0000000-a123-48ce-896b-4c76973373e6", properties=["read"]),
    ]

    class Scanner:
        def __init__(self, detection_callback, service_uuids, scanning_mode):
            assert scanning_mode == "active"
            info["filter"] = service_uuids
            self.callback = detection_callback

        async def __aenter__(self):
            self.callback(
                SimpleNamespace(name="sensitive-phone-name", address="11:22:33:44:55:66"),
                SimpleNamespace(service_uuids=[str(UUID_TEST)]),
            )
            return self

        async def __aexit__(self, *_args):
            return None

    class Client:
        def __init__(self, _device, timeout):
            assert timeout == 10.0
            self.is_connected = True
            self.services = SimpleNamespace(get_service=self.get_service)

        def get_service(self, uuid):
            assert uuid == str(UUID_TEST)
            return SimpleNamespace(characteristics=characteristic_list)

        async def __aenter__(self):
            info["connected"] = True
            return self

        async def __aexit__(self, *_args):
            info["disconnected"] = True
            return None

        async def read_gatt_char(self, *_args):
            raise AssertionError("Must not read GATT values")

        async def write_gatt_char(self, *_args):
            raise AssertionError("Must not write GATT values")

        async def start_notify(self, *_args):
            raise AssertionError("Must not subscribe to notifications")

    monkeypatch.setitem(sys.modules, "bleak", SimpleNamespace(
        BleakScanner=Scanner, BleakClient=Client
    ))
    result = asyncio.run(_discover_gatt(UUID_TEST, 3))
    assert result == _good()
    assert info["filter"] == [str(UUID_TEST)]
    assert info["connected"] is True
    assert info["disconnected"] is True
    assert "11:22" not in json.dumps(result)
    assert "sensitive-phone-name" not in json.dumps(result)


def test_cli_gatt_check_with_explicit_consent(monkeypatch, capsys):
    from tools.idc_diagnostic.__main__ import main

    monkeypatch.setattr(
        "tools.idc_diagnostic.__main__.capture_serial",
        lambda port, baudrate, timeout_seconds: _raw(),
    )

    def fake_gatt(raw_qr, *, consent, timeout_seconds):
        assert raw_qr == _raw()
        assert consent is True
        assert timeout_seconds == 30
        return {"status": "gatt_profile_discovered_not_session_started", "verified_identity": False}

    monkeypatch.setattr("tools.idc_diagnostic.__main__.probe_mdoc_ble_gatt", fake_gatt)
    assert main(["--ble-gatt-check", "--port", "COM5", "--consent", "--ble-scan-seconds", "30"]) == 0
    output = capsys.readouterr().out
    assert '"verified_identity": false' in output
    assert "synthetic-bytes" not in output


def test_cli_gatt_requires_consent_before_opening_port(monkeypatch):
    from tools.idc_diagnostic.__main__ import main

    monkeypatch.setattr(
        "tools.idc_diagnostic.__main__.capture_serial",
        lambda *_args, **_kwargs: pytest.fail("Port should not open"),
    )
    with pytest.raises(SystemExit):
        main(["--ble-gatt-check", "--port", "COM5"])
