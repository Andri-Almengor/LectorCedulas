from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

from assets.runtime.hardened.atomic_io import read_json, write_json_atomic
from assets.runtime.hardened.instance_control import MUTEX_NAME, signal_running_instance
from assets.runtime.hardened.privacy import build_logger, technical_event
from assets.runtime.hardened.runtime_state import (
    SUPERVISOR_MUTEX_NAME,
    resume_automatic_restart,
    suspend_automatic_restart,
)
from assets.runtime.hardened.update_manifest import (
    ManifestError,
    sha256_file,
    verify_manifest,
)
from assets.runtime.hardened.version import VERSION

EXECUTABLE_NAME = "LectorCedulasDMS.exe"
_SYNCHRONIZE = 0x00100000
_PROTECTED_EXACT_PATHS = {("licencia.key",)}
_PROTECTED_CONFIG_PREFIXES = {
    ("configs", "formularios"),
    ("configs", "sistema"),
}
_MANAGED_CONFIG_PREFIX = ("configs", "formatos")


class UpdateError(RuntimeError):
    pass


def _path_parts(value: str) -> tuple[str, ...]:
    return tuple(part.casefold() for part in Path(value).parts)


def _starts_with(parts: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return len(parts) >= len(prefix) and parts[: len(prefix)] == prefix


def _validate_update_target(value: str) -> None:
    """Protege datos del cliente y permite solo el catálogo administrado.

    El manifest ya garantiza rutas relativas seguras. Esta segunda barrera define
    qué rutas firmadas puede reemplazar el actualizador: licencia, formularios y
    estado local nunca se tocan; dentro de ``configs`` únicamente se administra
    el catálogo oficial ``formatos``.
    """
    parts = _path_parts(value)
    if parts in _PROTECTED_EXACT_PATHS:
        raise UpdateError(f"El manifest intenta reemplazar datos preservados: {value}")
    if any(_starts_with(parts, prefix) for prefix in _PROTECTED_CONFIG_PREFIXES):
        raise UpdateError(f"El manifest intenta reemplazar datos preservados: {value}")
    if parts and parts[0] == "configs" and not _starts_with(
        parts,
        _MANAGED_CONFIG_PREFIX,
    ):
        raise UpdateError(f"Ruta de configuración no administrada: {value}")


def _mutex_api():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _named_mutex_exists(name: str) -> bool:
    if os.name != "nt":
        return False
    kernel32 = _mutex_api()
    handle = kernel32.OpenMutexW(_SYNCHRONIZE, False, name)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def _wait_for_named_mutex_release(name: str, timeout: float) -> bool:
    """Espera hasta que ningún proceso mantenga abierto el mutex nombrado.

    Los mutex de instancia se crean sin propiedad inicial; por eso esperar con
    WaitForSingleObject no demostraría que el proceso terminó. La señal correcta
    es que OpenMutexW deje de encontrar el objeto cuando se cierre el último handle.
    """
    if os.name != "nt":
        return True
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if not _named_mutex_exists(name):
            return True
        time.sleep(0.05)
    return not _named_mutex_exists(name)


def _wait_for_application_exit(timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    for name in (MUTEX_NAME, SUPERVISOR_MUTEX_NAME):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not _wait_for_named_mutex_release(name, remaining):
            return False
    return True


def _wait_for_unlock(path: Path, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with path.open("a+b"):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def _restart_application(executable: Path, install_dir: Path) -> None:
    if not executable.is_file():
        return
    try:
        subprocess.Popen(
            [str(executable)],
            cwd=install_dir,
            close_fds=True,
        )
    except OSError:
        pass


def _verify_payload(payload_root: Path, files) -> None:
    for entry in files:
        _validate_update_target(entry.path)
        path = payload_root / Path(entry.path)
        if not path.is_file():
            raise UpdateError(f"Falta archivo del update: {entry.path}")
        if path.stat().st_size != entry.size:
            raise UpdateError(f"Tamaño inválido: {entry.path}")
        if sha256_file(path) != entry.sha256:
            raise UpdateError(f"Hash inválido: {entry.path}")


def _copy_to_stage(payload_root: Path, stage: Path, files) -> None:
    for entry in files:
        source = payload_root / Path(entry.path)
        destination = stage / Path(entry.path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _backup_existing(install_dir: Path, backup: Path, files) -> None:
    for entry in files:
        source = install_dir / Path(entry.path)
        if source.exists():
            destination = backup / Path(entry.path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def _replace_from_stage(install_dir: Path, stage: Path, files) -> None:
    for entry in files:
        _validate_update_target(entry.path)
        source = stage / Path(entry.path)
        destination = install_dir / Path(entry.path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".update-new")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)


def _rollback(install_dir: Path, backup: Path, files) -> None:
    for entry in files:
        backup_file = backup / Path(entry.path)
        destination = install_dir / Path(entry.path)
        if backup_file.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".rollback")
            shutil.copy2(backup_file, temporary)
            os.replace(temporary, destination)
        elif destination.exists():
            destination.unlink()


def _smoke_test(install_dir: Path) -> None:
    executable = install_dir / EXECUTABLE_NAME
    if not executable.is_file() or executable.stat().st_size < 1024:
        raise UpdateError("Smoke test falló: ejecutable principal ausente o inválido")


def apply_update(
    package_dir: Path,
    install_dir: Path,
    *,
    allow_downgrade: bool = False,
) -> str:
    logger = build_logger(install_dir / "logs", name="dms_updater")
    envelope = read_json(package_dir / "manifest.json", required=True)
    payload_root = package_dir / "payload"
    version, files = verify_manifest(
        envelope,
        public_key_path=install_dir / "assets" / "update_public_key.pem",
        current_version=VERSION,
        allow_downgrade=allow_downgrade,
    )
    _verify_payload(payload_root, files)

    executable = install_dir / EXECUTABLE_NAME
    runtime_was_active = _named_mutex_exists(MUTEX_NAME) or _named_mutex_exists(
        SUPERVISOR_MUTEX_NAME
    )
    suspend_automatic_restart()
    work_root: Path | None = None
    try:
        signal_running_instance()
        if runtime_was_active and not _wait_for_application_exit():
            raise UpdateError(
                "La aplicación o su supervisor no finalizaron dentro del tiempo permitido"
            )
        if executable.exists() and not _wait_for_unlock(executable):
            raise UpdateError("El ejecutable continúa bloqueado después del cierre")

        work_root = Path(
            tempfile.mkdtemp(prefix="dms-update-", dir=str(install_dir.parent))
        )
        stage = work_root / "stage"
        backup = work_root / "backup"
        stage.mkdir()
        backup.mkdir()
        try:
            _copy_to_stage(payload_root, stage, files)
            _backup_existing(install_dir, backup, files)
            _replace_from_stage(install_dir, stage, files)
            _smoke_test(install_dir)
            write_json_atomic(
                install_dir / "update_result.json",
                {
                    "status": "ok",
                    "version": version,
                    "updated_at_utc": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ",
                        time.gmtime(),
                    ),
                },
                backup=False,
            )
            logger.info(technical_event("update_applied", version=version))
            return version
        except Exception:
            _rollback(install_dir, backup, files)
            logger.exception(technical_event("update_rolled_back", version=version))
            raise
    finally:
        if work_root is not None:
            shutil.rmtree(work_root, ignore_errors=True)
        resume_automatic_restart()
        if runtime_was_active:
            _restart_application(executable, install_dir)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Actualizador seguro del Lector de Cédulas DMS"
    )
    parser.add_argument(
        "--package",
        default=os.path.dirname(
            sys.executable if getattr(sys, "frozen", False) else __file__
        ),
    )
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--allow-downgrade", action="store_true")
    args = parser.parse_args(argv)
    try:
        version = apply_update(
            Path(args.package),
            Path(args.install_dir),
            allow_downgrade=args.allow_downgrade,
        )
        print(f"Actualización aplicada: {version}")
        return 0
    except (ManifestError, UpdateError, OSError, ValueError) as exc:
        print(f"Actualización fallida: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
