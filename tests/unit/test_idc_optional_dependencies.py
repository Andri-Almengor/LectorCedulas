"""Aislamiento de dependencias para utilidades de diagnóstico aisladas."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]


def _run_isolated(*args: str) -> subprocess.CompletedProcess[str]:
    # -S evita cargar paquetes instalados en site-packages.
    # Un diagnóstico sano debe funcionar sin cryptography ni PyInstaller.
    return subprocess.run(
        [sys.executable, "-S", *args],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_importing_tools_does_not_import_build_or_crypto_dependencies():
    completed = _run_isolated(
        "-c",
        "import sys; import tools; "
        "assert 'tools.release_builder' not in sys.modules; "
        "assert 'cryptography' not in sys.modules; print('isolated')",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "isolated"


def test_bluetooth_diagnostic_runs_without_site_packages():
    completed = _run_isolated("-m", "tools.idc_diagnostic", "--bluetooth-check")
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["purpose"] == "hardware_diagnostic_only"
    assert report["ble_session_supported"] == "not_tested"
    assert report["idc_verification_available"] is False


def test_qr_diagnostic_sample_runs_without_site_packages():
    completed = _run_isolated(
        "-m",
        "tools.idc_diagnostic",
        "--sample-file",
        "tests/fixtures/idc_mdoc_synthetic.txt",
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["classification"] == "mdoc_candidate"
    assert report["verified_identity"] is False


def test_inno_guard_remains_active_for_builder_import():
    # Esta comprobación ocurre en el proceso normal del test, que sí instala
    # las dependencias del constructor.
    from tools import release_builder

    assert getattr(release_builder._write_inno, "_dms_inno_guard", False) is True


def test_ble_diagnostic_runs_without_site_packages():
    completed = _run_isolated("-m", "tools.idc_diagnostic", "--ble-capabilities")
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["purpose"] == "ble_capability_diagnostic_only"
    assert report["idc_verification_available"] is False
    assert report["verified_identity"] is False
