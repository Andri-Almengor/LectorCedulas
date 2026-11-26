"""Codificador de fragmentos GATT sin radios ni dispositivos reales."""
from __future__ import annotations

import pytest

from tools.idc_diagnostic.gatt_codec import (
    CLIENT_TO_SERVER_UUID,
    SERVER_TO_CLIENT_UUID,
    STATE_END,
    STATE_START,
    STATE_UUID,
    GattCodecError,
    GattReassembler,
    fragment_message,
)


@pytest.mark.parametrize("mtu,payload_size", [(23, 1), (23, 19), (23, 20), (23, 100), (100, 1000)])
def test_fragmentation_roundtrip(mtu, payload_size):
    raw = bytes((i % 251 for i in range(payload_size)))
    fragments = fragment_message(raw, mtu=mtu)
    assert fragments
    assert all(len(frame) <= mtu - 3 for frame in fragments)
    assert all(part[0] == 1 for part in fragments[:-1])
    assert fragments[-1][0] == 0
    reassembler = GattReassembler()
    results = [reassembler.accept(part) for part in fragments]
    assert all(result is None for result in results[:-1])
    assert results[-1] == raw


def test_extra_fragment_after_end_rejected():
    receiver = GattReassembler()
    assert receiver.accept(b"\x00valid") == b"valid"
    with pytest.raises(GattCodecError, match="message_already_complete"):
        receiver.accept(b"\x00again")


def test_corrupt_prefix_fails_without_exposing_content():
    receiver = GattReassembler()
    with pytest.raises(GattCodecError, match="invalid_fragment_marker"):
        receiver.accept(b"\x02secret")
    assert "secret" not in repr(receiver)


def test_size_limit_and_mtu_validation():
    with pytest.raises(GattCodecError, match="invalid_gatt_mtu"):
        fragment_message(b"a", mtu=18)
    with pytest.raises(GattCodecError, match="invalid_session_payload"):
        fragment_message(b"", mtu=23)
    receiver = GattReassembler(max_bytes=8)
    assert receiver.accept(b"\x01" + b"A" * 5) is None
    with pytest.raises(GattCodecError, match="message_too_large"):
        receiver.accept(b"\x00" + b"A" * 4)


def test_uuid_and_state_constants():
    assert STATE_UUID.startswith("00000001-")
    assert CLIENT_TO_SERVER_UUID.startswith("00000002-")
    assert SERVER_TO_CLIENT_UUID.startswith("00000003-")
    assert STATE_START == b"\x01"
    assert STATE_END == b"\x02"
