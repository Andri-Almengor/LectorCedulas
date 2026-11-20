"""Prueba BLE limitada a UUID de una sesión sintética y sin credenciales reales."""
from __future__ import annotations

import base64
import json
from uuid import UUID

from tools.idc_diagnostic.ble_link_probe import probe_mdoc_ble_link

UUID_TEST = UUID("6fa459a1-6bd5-486b-8b59-1c375ee613d1")


def _sample() -> bytes:
    # Los bytes CBOR se sustituyen por decodificación controlada en los tests.
    return b"mdoc:" + base64.urlsafe_b64encode(b"synthetic-cbor-not-a-real-idc").rstrip(b"=")


def _engagement(_raw: bytes):
    return {
        0: "1.0",
        1: [1, b"synthetic-ephemeral-data"],
        2: [[2, 1, {0: True, 1: False, 10: UUID_TEST.bytes}]],
    }


async def _success(uuid: UUID, timeout: float):
    assert uuid == UUID_TEST
    assert timeout >= 3
    return True, True


async def _not_found(_uuid: UUID, _timeout: float):
    return False, False


async def _link_fail(_uuid: UUID, _timeout: float):
    return True, False


def test_successful_link_never_means_verified_idc():
    result = probe_mdoc_ble_link(_sample(), consent=True, decode_cbor=_engagement, connect=_success)
    assert result["holder_peripheral_announced"] is True
    assert result["ble_service_uuid_present"] is True
    assert result["link_status"] == "link_opened_then_closed"
    assert result["ble_link_established"] is True
    assert result["mdoc_session_established"] is False
    assert result["verified_identity"] is False
    assert result["idc_verification_available"] is False
    assert str(UUID_TEST) not in json.dumps(result)


def test_missing_explicit_consent_prevents_all_activities():
    def unexpected(_raw: bytes):
        raise AssertionError("No parse allowed")
    result = probe_mdoc_ble_link(_sample(), consent=False, decode_cbor=unexpected)
    assert result["link_status"] == "consent_required"
    assert result["ble_link_established"] is False


def test_connection_not_found_is_not_claimed_success():
    result = probe_mdoc_ble_link(_sample(), consent=True, decode_cbor=_engagement, connect=_not_found)
    assert result["link_status"] == "service_not_found"
    assert result["verified_identity"] is False


def test_connection_failed_is_not_claimed_success():
    result = probe_mdoc_ble_link(_sample(), consent=True, decode_cbor=_engagement, connect=_link_fail)
    assert result["link_status"] == "connection_not_established"
    assert result["ble_link_established"] is False


def test_phone_central_mode_needs_reader_peripheral_implementation():
    def central_only(_raw: bytes):
        return {0: "1.0", 2: [[2, 1, {0: False, 1: True, 11: UUID_TEST.bytes}]]}
    report = probe_mdoc_ble_link(_sample(), consent=True, decode_cbor=central_only, connect=_success)
    assert report["link_status"] == "phone_central_mode_only"
    assert report["holder_central_announced"] is True
    assert report["ble_link_established"] is False


def test_broken_and_non_mdoc_qr_rejected_without_ble():
    for bad in (b"https://tse.go.cr", b"mdoc:@@@", b"mdoc:"):
        report = probe_mdoc_ble_link(bad, consent=True, decode_cbor=_engagement, connect=_success)
        assert report["link_status"] == "invalid_qr"
        assert report["ble_link_established"] is False


def test_mdoc_not_convertible_to_cbor_never_starts_ble():
    def malformed(_raw: bytes):
        raise ValueError("malformed")
    report = probe_mdoc_ble_link(_sample(), consent=True, decode_cbor=malformed, connect=_success)
    assert report["link_status"] == "invalid_cbor"
    assert report["verified_identity"] is False


def test_invalid_uuid_no_link():
    def baduuid(_raw: bytes):
        return {0: "1.0", 2: [[2, 1, {0: True, 1: False, 10: b"wrong"}]]}
    report = probe_mdoc_ble_link(_sample(), consent=True, decode_cbor=baduuid, connect=_success)
    assert report["link_status"] == "missing_peripheral_uuid"
    assert report["ble_link_established"] is False


def test_local_scan_error_does_not_leak_identifiers():
    async def failed(uuid: UUID, _timeout: float):
        raise RuntimeError(f"Device UUID {uuid}; MAC 11:22:33:44:55:66")
    report = probe_mdoc_ble_link(_sample(), consent=True, decode_cbor=_engagement, connect=failed)
    assert report["link_status"] == "bluetooth_connection_error"
    assert str(UUID_TEST) not in json.dumps(report)
    assert "11:22" not in json.dumps(report)


def test_link_timeout_bounds():
    report = probe_mdoc_ble_link(_sample(), consent=True, decode_cbor=_engagement, connect=_success, timeout_seconds=60)
    assert report["link_status"] == "invalid_timeout"
