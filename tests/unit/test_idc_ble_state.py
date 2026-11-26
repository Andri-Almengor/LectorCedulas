"""Señalización ISO 18013-5 State Start/End sin solicitar datos personales."""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from types import SimpleNamespace
from uuid import UUID

import pytest

from tools.idc_diagnostic.ble_state_probe import (
    _try_state_handshake,
    probe_mdoc_ble_state,
)
from tools.idc_diagnostic.gatt_codec import (
    CLIENT_TO_SERVER_UUID, SERVER_TO_CLIENT_UUID, STATE_END, STATE_START, STATE_UUID,
)

TEST_UUID = UUID("6fa459a1-6bd5-486b-8b59-1c375ee613d1")


def _sample():
    return b"mdoc:" + base64.urlsafe_b64encode(b"synthetic-test-only").rstrip(b"=")


def _engagement(_raw):
    return {0: "1.0", 2: [[2, 1, {0: True, 1: False, 10: TEST_UUID.bytes}]]}


def _good():
    return {
        "device_found": True,
        "ble_connected": True,
        "gatt_service_found": True,
        "required_properties_present": True,
        "state_notify_subscribed": True,
        "server_to_client_notify_subscribed": True,
        "state_start_sent": True,
        "state_end_sent": True,
        "peer_end_observed": True,
        "unrequested_data_notification_seen": False,
        "notification_unsubscribe_completed": True,
    }


async def _mock_success(uuid: UUID, seconds: float):
    assert uuid == TEST_UUID and seconds == 30
    return _good()


async def _no_service(_uuid: UUID, _seconds: float):
    return {"device_found": False}


async def _no_props(_uuid: UUID, _seconds: float):
    return {**_good(), "required_properties_present": False,
            "state_start_sent": False, "state_end_sent": False}


async def _start_only(_uuid: UUID, _seconds: float):
    return {**_good(), "state_end_sent": False}


def test_successful_start_end_is_not_mdoc_session_or_identity():
    r = probe_mdoc_ble_state(
        _sample(), consent=True, allow_gatt_write=True,
        decode_cbor=_engagement, handshake=_mock_success,
    )
    assert r["status"] == "state_start_and_end_sent_no_document_request"
    assert r["state_notify_subscribed"]
    assert r["server_to_client_notify_subscribed"]
    assert r["state_start_sent"] and r["state_end_sent"]
    assert not r["client_to_server_data_sent"]
    assert not r["device_request_sent"]
    assert not r["mdoc_session_established"]
    assert not r["verified_identity"]
    assert str(TEST_UUID) not in json.dumps(r)


@pytest.mark.parametrize("consent,allow", [(False, False), (True, False), (False, True)])
def test_requires_consent_and_explicit_gatt_write_permission(consent, allow):
    def forbidden(_raw):
        raise AssertionError("Must not decode QR or connect without permission")

    r = probe_mdoc_ble_state(
        _sample(), consent=consent, allow_gatt_write=allow,
        decode_cbor=forbidden,
    )
    assert r["status"] == "consent_and_write_permission_required"
    assert not r["ble_link_established"]


@pytest.mark.parametrize(
    "handshake,status",
    [
        (_no_service, "service_not_found"),
        (_no_props, "required_gatt_properties_missing"),
        (_start_only, "state_start_sent_end_not_confirmed"),
    ],
)
def test_reports_partial_outcomes_without_claiming_verification(handshake, status):
    r = probe_mdoc_ble_state(
        _sample(), consent=True, allow_gatt_write=True,
        decode_cbor=_engagement, handshake=handshake,
    )
    assert r["status"] == status
    assert r["verified_identity"] is False


def test_state_signaling_subscribes_first_then_writes_only_state(monkeypatch):
    activity = []
    service_uuid = str(TEST_UUID)
    chars = [
        SimpleNamespace(uuid=STATE_UUID, properties=["notify", "write-without-response"]),
        SimpleNamespace(uuid=CLIENT_TO_SERVER_UUID, properties=["write-without-response"]),
        SimpleNamespace(uuid=SERVER_TO_CLIENT_UUID, properties=["notify"]),
    ]

    class FakeScanner:
        def __init__(self, *, detection_callback, service_uuids, scanning_mode):
            assert service_uuids == [service_uuid]
            assert scanning_mode == "active"
            self.cb = detection_callback

        async def __aenter__(self):
            activity.append("scan")
            self.cb(
                SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="sensitive-name"),
                SimpleNamespace(service_uuids=[service_uuid]),
            )
            return self

        async def __aexit__(self, *_args):
            activity.append("stop_scan")

    class FakeClient:
        def __init__(self, _device, timeout):
            assert timeout == 10
            self.is_connected = True
            self.services = SimpleNamespace(get_service=self.get_service)

        def get_service(self, uuid):
            assert uuid == service_uuid
            return SimpleNamespace(characteristics=chars)

        async def __aenter__(self):
            activity.append("connect")
            return self

        async def __aexit__(self, *_args):
            activity.append("disconnect")
            self.is_connected = False

        async def start_notify(self, characteristic, callback):
            activity.append("subscribe:" + characteristic.uuid)
            if characteristic.uuid == STATE_UUID:
                callback(characteristic, bytearray(STATE_END))

        async def stop_notify(self, characteristic):
            activity.append("unsubscribe:" + characteristic.uuid)

        async def write_gatt_char(self, characteristic, payload, *, response):
            assert characteristic.uuid == STATE_UUID, "Never transmit document request"
            assert response is False
            activity.append("write:" + bytes(payload).hex())

        async def read_gatt_char(self, *_args):
            raise AssertionError("No personal data reads allowed")

    monkeypatch.setitem(
        sys.modules, "bleak",
        SimpleNamespace(BleakScanner=FakeScanner, BleakClient=FakeClient),
    )
    details = asyncio.run(_try_state_handshake(TEST_UUID, 3))
    assert details["state_start_sent"] and details["state_end_sent"]
    assert details["peer_end_observed"]
    assert details["notification_unsubscribe_completed"]
    assert activity.index("subscribe:" + STATE_UUID) < activity.index("write:01")
    assert activity.index("subscribe:" + SERVER_TO_CLIENT_UUID) < activity.index("write:01")
    assert "write:01" in activity and "write:02" in activity
    assert activity.index("write:02") < activity.index("disconnect")
    assert "sensitive-name" not in json.dumps(details)
    assert "AA:BB" not in json.dumps(details)


def test_missing_write_without_response_property_never_sends_start(monkeypatch):
    activity = []
    chars = [
        SimpleNamespace(uuid=STATE_UUID, properties=["notify", "write"]),
        SimpleNamespace(uuid=CLIENT_TO_SERVER_UUID, properties=["write-without-response"]),
        SimpleNamespace(uuid=SERVER_TO_CLIENT_UUID, properties=["notify"]),
    ]

    class Scanner:
        def __init__(self, *, detection_callback, **_kwargs):
            self.callback = detection_callback

        async def __aenter__(self):
            self.callback(object(), SimpleNamespace(service_uuids=[str(TEST_UUID)]))
            return self

        async def __aexit__(self, *_args):
            pass

    class Client:
        def __init__(self, *_args, **_kwargs):
            self.is_connected = True
            self.services = SimpleNamespace(
                get_service=lambda _uuid: SimpleNamespace(characteristics=chars)
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def write_gatt_char(self, *_args, **_kwargs):
            activity.append("write")

        async def start_notify(self, *_args):
            activity.append("subscribe")

    monkeypatch.setitem(
        sys.modules, "bleak",
        SimpleNamespace(BleakScanner=Scanner, BleakClient=Client),
    )
    details = asyncio.run(_try_state_handshake(TEST_UUID, 3))
    assert details["required_properties_present"] is False
    assert details["state_start_sent"] is False
    assert activity == []


def test_cli_state_check_requires_write_permission_before_capture(monkeypatch):
    from tools.idc_diagnostic.__main__ import main

    def prohibited(*_args, **_kwargs):
        pytest.fail("COM port must not open without permission")

    monkeypatch.setattr("tools.idc_diagnostic.__main__.capture_serial", prohibited)
    with pytest.raises(SystemExit):
        main(["--ble-state-check", "--port", "COM5", "--consent"])


def test_cli_state_check_emits_only_flags(monkeypatch, capsys):
    from tools.idc_diagnostic.__main__ import main

    monkeypatch.setattr(
        "tools.idc_diagnostic.__main__.capture_serial",
        lambda *_args, **_kwargs: _sample(),
    )

    def probe(raw_qr, *, consent, allow_gatt_write, timeout_seconds):
        assert raw_qr == _sample()
        assert consent and allow_gatt_write and timeout_seconds == 30
        return {"status": "state_start_and_end_sent_no_document_request",
                "verified_identity": False}

    monkeypatch.setattr("tools.idc_diagnostic.__main__.probe_mdoc_ble_state", probe)
    assert main([
        "--ble-state-check", "--port", "COM5", "--consent",
        "--allow-gatt-write", "--ble-scan-seconds", "30",
    ]) == 0
    out = capsys.readouterr().out
    assert "synthetic-test-only" not in out
    assert "verified_identity" in out
