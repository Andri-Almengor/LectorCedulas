from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from assets.runtime.hardened.format_engine import DeclarativeFormatEngine
from assets.runtime.hardened.reader_calibration import PortCalibrationService
from tools import release_builder


class FakeSerial:
    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.closed = False

    @property
    def in_waiting(self) -> int:
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, _size: int) -> bytes:
        return self.chunks.pop(0)

    def close(self) -> None:
        self.closed = True


def test_calibration_starts_with_saved_port_and_keeps_valid_scan() -> None:
    opened: list[str] = []
    saved: list[dict] = []
    serials = {
        "COM3": FakeSerial([]),
        "COM8": FakeSerial([b"VALID-123"]),
    }

    def open_port(device: str, _baudrate: int, _timeout: float) -> FakeSerial:
        opened.append(device)
        return serials[device]

    service = PortCalibrationService(
        list_ports=lambda: [
            SimpleNamespace(device="COM3", vid=3, pid=3),
            SimpleNamespace(device="COM8", vid=8, pid=8),
        ],
        open_port=open_port,
        validate_frame=lambda raw: raw == b"VALID-123",
        load_last_port=lambda: {"device": "COM8", "vid": 8, "pid": 8},
        save_last_port=saved.append,
        idle_seconds=0.001,
        per_port_timeout=0.04,
    )

    result = service.calibrate()

    assert result.success
    assert result.identity is not None
    assert result.identity.device == "COM8"
    assert opened == ["COM8"]
    assert saved[0]["device"] == "COM8"


def test_calibration_moves_to_next_port_after_timeout() -> None:
    opened: list[str] = []
    saved: list[dict] = []
    serials = {
        "COM3": FakeSerial([]),
        "COM4": FakeSerial([b"DOCUMENTO"]),
    }

    def open_port(device: str, _baudrate: int, _timeout: float) -> FakeSerial:
        opened.append(device)
        return serials[device]

    service = PortCalibrationService(
        list_ports=lambda: [
            SimpleNamespace(device="COM3"),
            SimpleNamespace(device="COM4"),
        ],
        open_port=open_port,
        validate_frame=lambda raw: raw == b"DOCUMENTO",
        load_last_port=lambda: {"device": "COM3"},
        save_last_port=saved.append,
        idle_seconds=0.001,
        per_port_timeout=0.03,
    )

    result = service.calibrate(preferred_device="COM3")

    assert result.success
    assert opened == ["COM3", "COM4"]
    assert saved[0]["device"] == "COM4"


def test_calibration_returns_retryable_result_when_no_ports_exist() -> None:
    service = PortCalibrationService(
        list_ports=lambda: [],
        open_port=lambda *_args: FakeSerial([]),
        validate_frame=lambda _raw: True,
        load_last_port=lambda: {},
        save_last_port=lambda _data: None,
        per_port_timeout=0.01,
    )

    result = service.calibrate()

    assert not result.success
    assert result.identity is None
    assert "No se encontraron puertos COM" in result.message


def test_inno_offers_desktop_and_windows_startup_shortcuts(
    tmp_path: Path,
) -> None:
    build_root = tmp_path / "build"
    app_dir = tmp_path / "app"
    out_dir = tmp_path / "out"
    build_root.mkdir()
    app_dir.mkdir()
    out_dir.mkdir()

    script = release_builder._write_inno(
        build_root,
        app_dir,
        out_dir,
        "CLIENTE_PRUEBA",
        icon=False,
    )
    content = script.read_text(encoding="utf-8")

    assert 'Name: "desktopicon"' in content
    assert 'Name: "startup"' in content
    assert 'Name: "{autodesktop}\\{#MyAppName}"' in content
    assert 'Name: "{userstartup}\\{#MyAppName}"' in content
    assert "Flags: checkedonce" in content


def test_sbom_failure_does_not_block_installer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    work = tmp_path / "work"
    log = tmp_path / "build.log"
    destination = tmp_path / "sbom.cdx.json"
    work.mkdir()

    monkeypatch.setattr(release_builder.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        release_builder,
        "_run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
    )

    assert not release_builder._generate_sbom(work, destination, log)
    assert "continuará" in log.read_text(encoding="utf-8")


def formats_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "template"
        / "configs"
        / "formatos"
        / "formatos_cedulas.json"
    )


def test_packaged_catalog_contains_all_user_formats() -> None:
    expected = {
        "MENOR_CSV",
        "ADULTO_XOR_CLASICO",
        "LICENCIA_CONDUCIR_BINARIA_V1",
        "CEDULA_CSV_EXTENDIDA_V2",
        "CODIGO_CORTO_CI",
        "TSE_QR_URL",
        "TSE_MDOC_ISO18013",
    }
    payload = json.loads(formats_path().read_text(encoding="utf-8"))
    assert payload["version"] == 6
    assert {item["id"] for item in payload["formatos"]} == expected


def test_packaged_short_code_format_is_readable() -> None:
    match = DeclarativeFormatEngine(formats_path()).parse(b"CI119320121B1")
    assert match is not None
    assert match.format_id == "CODIGO_CORTO_CI"
    assert match.data["Cedula"] == "119320121"
