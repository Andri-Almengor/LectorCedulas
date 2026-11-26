"""Fragmentación BLE-GATT ISO/IEC 18013-5 (mDoc periférico, lector central).

Codec PURO: no abre conexiones ni solicita credenciales. Solo trata bytes
cifrados o sintéticos; no debe recibir datos personales sin haber autenticado.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# GATT service UUID es efímero y proviene del DeviceEngagement del QR.
# Estos son los UUID fijos de las características del perfil mdoc periférico.
STATE_UUID = "00000001-a123-48ce-896b-4c76973373e6"
CLIENT_TO_SERVER_UUID = "00000002-a123-48ce-896b-4c76973373e6"
SERVER_TO_CLIENT_UUID = "00000003-a123-48ce-896b-4c76973373e6"
STATE_START = b"\x01"
STATE_END = b"\x02"
MAX_SESSION_MESSAGE = 1024 * 1024


class GattCodecError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def fragment_message(payload: bytes, *, mtu: int = 23) -> tuple[bytes, ...]:
    """Prefijo 0x01 = continúan partes, 0x00 = última. MTU-3 bytes por envío."""
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_SESSION_MESSAGE:
        raise GattCodecError("invalid_session_payload")
    if not isinstance(mtu, int) or not 23 <= mtu <= 517:
        raise GattCodecError("invalid_gatt_mtu")
    # ATT Write Without Response ocupa 3 bytes; la bandera de mdoc ocupa 1.
    chunk_size = mtu - 4
    result = []
    for offset in range(0, len(payload), chunk_size):
        end = offset + chunk_size
        more = b"\x01" if end < len(payload) else b"\x00"
        result.append(more + payload[offset:end])
    return tuple(result)


@dataclass(repr=False)
class GattReassembler:
    max_bytes: int = MAX_SESSION_MESSAGE
    _buffer: bytearray = field(default_factory=bytearray, repr=False)
    _completed: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.max_bytes <= MAX_SESSION_MESSAGE:
            raise GattCodecError("invalid_max_size")

    def __repr__(self) -> str:
        return "<GattReassembler (payload redacted)>"

    def accept(self, frame: bytes) -> bytes | None:
        """Reensambla una sola respuesta, sin imprimir ni aceptar múltiples mensajes."""
        if self._completed:
            raise GattCodecError("message_already_complete")
        if not isinstance(frame, bytes) or len(frame) < 2:
            self._buffer.clear()
            raise GattCodecError("invalid_gatt_fragment")
        marker = frame[0]
        if marker not in (0, 1):
            self._buffer.clear()
            raise GattCodecError("invalid_fragment_marker")
        if len(self._buffer) + len(frame) - 1 > self.max_bytes:
            self._buffer.clear()
            raise GattCodecError("message_too_large")
        self._buffer.extend(frame[1:])
        if marker == 1:
            return None
        self._completed = True
        return bytes(self._buffer)
