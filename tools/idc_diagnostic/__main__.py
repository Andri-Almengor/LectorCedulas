"""CLI de captura segura para investigación de QR IDC."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .ble_capabilities import probe_ble_capabilities
from .ble_link_probe import probe_mdoc_ble_link
from .ble_gatt_probe import probe_mdoc_ble_gatt
from .ble_observer import observe_mdoc_ble_advertising
from .ble_runtime import probe_ble_runtime
from .bluetooth_probe import probe_bluetooth
from .capture import available_ports, capture_keyboard, capture_serial
from .inspect import MAX_SCAN_BYTES, inspect_qr
from .mdoc_core import preflight_mdoc_crypto


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
    source.add_argument("--ble-runtime-check", action="store_true", help="Comprueba importación Bleak/WinRT sin escanear el entorno")
    source.add_argument("--port", help="Lector USB/serial, por ejemplo COM3")
    source.add_argument("--keyboard", action="store_true", help="Lector USB que escribe como teclado")
    source.add_argument("--sample-file", help="Muestra local para pruebas; no compartir el archivo")
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--ble-link-check", action="store_true", help="Prueba enlace BLE al QR (requiere --port y --consent)")
    parser.add_argument("--ble-gatt-check", action="store_true", help="Descubre características GATT de mDoc sin leer valores ni escribir")
    parser.add_argument("--mdoc-preflight", action="store_true", help="ECDH local con QR mdoc; NO verifica identidad")
    parser.add_argument("--ble-observe-check", action="store_true", help="Observación BLE temporal sin filtro (requiere --nearby-scan-ok)")
    parser.add_argument("--nearby-scan-ok", action="store_true", help="Autoriza observar temporalmente anuncios BLE próximos, sin conservar identificadores")

    parser.add_argument("--ble-scan-seconds", type=float, default=18.0, help="Duración de búsqueda BLE dirigida (3 a 30 segundos; predeterminado 18)")
    parser.add_argument("--consent", action="store_true", help="Declara consentimiento del titular para prueba BLE presencial")
    parser.add_argument("--output", help="Guardar solo metadatos JSON; archivo nuevo")
    args = parser.parse_args(argv)

    if args.ble_observe_check and (
        not args.port or not args.consent or not args.nearby_scan_ok
        or args.ble_link_check or args.mdoc_preflight
    ):
        parser.error("--ble-observe-check requiere --port COMx --consent --nearby-scan-ok; no combinar con otras pruebas")
    if args.nearby_scan_ok and not args.ble_observe_check:
        parser.error("--nearby-scan-ok solo corresponde a --ble-observe-check")
    if args.ble_observe_check and not 3 <= args.ble_scan_seconds <= 30:
        parser.error("--ble-scan-seconds debe estar entre 3 y 30")
    if args.ble_gatt_check and (
        not args.port or not args.consent or args.ble_link_check
        or args.ble_observe_check or args.mdoc_preflight
    ):
        parser.error("--ble-gatt-check requiere --port COMx --consent sin otras pruebas")
    if args.ble_gatt_check and not 3 <= args.ble_scan_seconds <= 30:
        parser.error("--ble-scan-seconds debe estar entre 3 y 30")
    if args.ble_link_check and (not args.port or not args.consent):
        parser.error("--ble-link-check requiere --port COMx y --consent")
    if args.mdoc_preflight and (not args.consent or (not args.port and not args.sample_file)):
        parser.error("--mdoc-preflight requiere --consent y --port COMx o --sample-file sintético")
    if args.mdoc_preflight and args.keyboard:
        parser.error("--mdoc-preflight no admite entrada de teclado HID")
    if args.ble_link_check and not 3 <= args.ble_scan_seconds <= 30:
        parser.error("--ble-scan-seconds debe estar entre 3 y 30")
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
        if args.ble_runtime_check:
            report = probe_ble_runtime()
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
            if args.ble_observe_check:
                print("Escanee el QR autorizado. Se observarán temporalmente anuncios BLE próximos sin guardar identificadores.")
            if args.ble_gatt_check:
                print("Escanee el QR autorizado. Se comprobarán solo características GATT sin leer atributos.")
            if args.ble_link_check:
                print("Presente el QR de la IDC autorizada al lector COM. No se guardará.")
            raw = capture_serial(args.port, baudrate=args.baudrate, timeout_seconds=args.timeout)
            if args.ble_gatt_check:
                report = probe_mdoc_ble_gatt(
                    raw, consent=True, timeout_seconds=args.ble_scan_seconds,
                )
                print(json.dumps(report, ensure_ascii=False, indent=2))
                if args.output:
                    _write_report(args.output, report)
                return 0

            if args.ble_observe_check:
                report = observe_mdoc_ble_advertising(
                    raw, consent=True, nearby_scan_ok=True,
                    duration_seconds=args.ble_scan_seconds,
                )
                print(json.dumps(report, ensure_ascii=False, indent=2))
                if args.output:
                    _write_report(args.output, report)
                return 0

            if args.ble_link_check:
                report = probe_mdoc_ble_link(raw, consent=True, timeout_seconds=args.ble_scan_seconds)
                print(json.dumps(report, ensure_ascii=False, indent=2))
                if args.output:
                    _write_report(args.output, report)
                return 0
        elif args.keyboard:
            raw = capture_keyboard()
        else:
            path = Path(args.sample_file)
            if path.stat().st_size > MAX_SCAN_BYTES:
                raise ValueError("Muestra local excede el límite de 32 KiB")
            raw = path.read_bytes()
        if args.mdoc_preflight:
            report = preflight_mdoc_crypto(raw, consent=True)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if args.output:
                _write_report(args.output, report)
            return 0
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
