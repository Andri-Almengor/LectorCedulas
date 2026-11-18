"""Captura aislada: jamás escribe sobre los formularios ni guarda datos brutos."""
from __future__ import annotations

import sys
import time

from .inspect import MAX_SCAN_BYTES


def available_ports() -> list[str]:
    import serial.tools.list_ports

    return [item.device for item in serial.tools.list_ports.comports()]


def capture_serial(
    port: str,
    *,
    baudrate: int = 9600,
    timeout_seconds: float = 25.0,
    silence_seconds: float = 0.45,
) -> bytes:
    import serial

    if not 0 < timeout_seconds <= 120:
        raise ValueError("Timeout fuera de rango")
    if not 0.05 <= silence_seconds <= 3:
        raise ValueError("Silencio fuera de rango")
    received = bytearray()
    started = time.monotonic()
    last_rx: float | None = None
    with serial.Serial(port, baudrate=baudrate, timeout=0.15) as reader:
        while time.monotonic() - started < timeout_seconds:
            chunk = reader.read(1024)
            now = time.monotonic()
            if chunk:
                received.extend(chunk)
                if len(received) > MAX_SCAN_BYTES:
                    raise ValueError("QR excede 32 KiB; lectura descartada")
                last_rx = now
            elif received and last_rx is not None and now - last_rx >= silence_seconds:
                return bytes(received)
    if received:
        return bytes(received)
    raise TimeoutError("No se recibió ninguna lectura")


def capture_keyboard() -> bytes:
    print("Enfoque esta consola, escanee el QR y presione Enter si es necesario.", flush=True)
    line = sys.stdin.buffer.readline(MAX_SCAN_BYTES + 2)
    if len(line) > MAX_SCAN_BYTES:
        raise ValueError("QR excede 32 KiB; lectura descartada")
    if not line:
        raise EOFError("No se recibió entrada")
    return line
