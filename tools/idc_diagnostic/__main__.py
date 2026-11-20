"""CLI de captura segura para investigación de QR IDC."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .ble_capabilities import probe_ble_capabilities
from .bluetooth_probe import probe_bluetooth
from .capture import available_ports, capture_keyboard, capture_serial
from .inspect import MAX_SCAN_BYTES, inspect_qr


def _write_report(destination: str, report: dict[str, object]) -> None:
    path = Path(destination)
    if not path.parent.is_dir():
        raise FileNotFoundError("La carpeta de salida no existe")
    # Escritura exclusiva, para no reemplazar diagnósticos previos.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspecciona METADATOS de un QR; no verifica identidades ni guarda el QR."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--list-ports", action="store_true", help="Lista puertos seriales disponibles")
    source.add_argument("--bluetooth-check", action="store_true", help="Estado Bluetooth local, sin buscar móviles")
    source.add_argument("--ble-capabilities", action="store_true", help="Capacidades BLE reales del adaptador Windows; WinRT opcional")
    source.add_argument("--port", help="Lector USB/serial, por ejemplo COM3")
    source.add_argument("--keyboard", action="store_true", help="Lector USB que escribe como teclado")
    source.add_argument("--sample-file", help="Muestra local para pruebas; no compartir el archivo")
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--output", help="Guardar solo metadatos JSON; archivo nuevo")
    args = parser.parse_args(argv)
    try:
        if args.list_ports:
            for device in available_ports():
                print(device)
            return 0
        if args.bluetooth_check:
            report = probe_bluetooth()
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if args.output:
                _write_report(args.output, report)
            return 0
        if args.ble_capabilities:
            report = probe_ble_capabilities()
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if args.output:
                _write_report(args.output, report)
            return 0
        if args.port:
            raw = capture_serial(args.port, baudrate=args.baudrate, timeout_seconds=args.timeout)
        elif args.keyboard:
            raw = capture_keyboard()
        else:
            path = Path(args.sample_file)
            if path.stat().st_size > MAX_SCAN_BYTES:
                raise ValueError("Muestra local excede el límite de 32 KiB")
            raw = path.read_bytes()
        report = inspect_qr(raw)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.output:
            _write_report(args.output, report)
            print("Informe de metadatos guardado. No contiene el QR original.")
        return 0
    except (OSError, ValueError, TimeoutError, EOFError) as exc:
        print(f"Error de captura: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
