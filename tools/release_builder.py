from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "template"
CLIENTS = ROOT / "clientes"

if str(TEMPLATE) not in sys.path:
    sys.path.insert(0, str(TEMPLATE))

from assets.runtime.hardened.atomic_io import write_json_atomic
from assets.runtime.hardened.license_service import generate_keypair, issue_license, parse_utc
from assets.runtime.hardened.update_manifest import build_file_entries, sign_manifest
from assets.runtime.hardened.version import PRODUCT_ID, PRODUCT_NAME, UPDATE_MANIFEST_SCHEMA_VERSION, VERSION


class BuildError(RuntimeError):
    pass


def _secret_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return base / "DMS" / "LectorCedulas" / "secrets"


def _ensure_keys(name: str) -> tuple[Path, Path]:
    secret = _secret_root()
    private = secret / f"{name}_private_key.pem"
    public = secret / f"{name}_public_key.pem"
    if not private.exists():
        generate_keypair(private, public)
    elif not public.exists():
        raise BuildError(f"Falta clave pública para {name}; no se regeneró la privada existente")
    return private, public


def _run(command: list[str], *, cwd: Path, log: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write("$ " + subprocess.list2cmdline(command) + "\n")
        handle.write(result.stdout)
        handle.write(result.stderr)
        handle.write(f"\nexit={result.returncode}\n")
    if result.returncode:
        raise BuildError(f"Comando falló ({result.returncode}); revise {log}")
    return result


def _pyinstaller() -> str:
    executable = shutil.which("pyinstaller")
    if not executable:
        raise BuildError("PyInstaller no está instalado")
    return executable


def _iscc() -> str:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    ]
    direct = shutil.which("ISCC.exe") or shutil.which("iscc")
    if direct:
        candidates.append(Path(direct))
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise BuildError("Inno Setup 6 no está instalado")


def _build_exe(work: Path, script: str, name: str, log: Path, *, console: bool = False) -> Path:
    command = [
        _pyinstaller(),
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        name,
        "--paths",
        str(work),
        "--hidden-import",
        "assets.runtime.hardened.app_runtime",
        "--hidden-import",
        "assets.runtime.hardened.windows_control",
    ]
    if not console:
        command.append("--noconsole")
    icon = work / "assets" / "DMS_icono_circulo_i.ico"
    if icon.exists():
        command.extend(["--icon", str(icon)])
    command.append(script)
    _run(command, cwd=work, log=log)
    output = work / "dist" / f"{name}.exe"
    if not output.is_file():
        raise BuildError(f"PyInstaller no generó {output.name}")
    return output


def _copy_template(work: Path) -> None:
    shutil.copytree(TEMPLATE, work, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _client_claims(client: dict[str, Any]) -> tuple[str, str, datetime, datetime]:
    license_data = client.get("license") or {}
    client_id = str(client.get("client_id") or "").strip()
    license_id = str(license_data.get("license_id") or f"LIC-{uuid.uuid4().hex[:12].upper()}").strip()
    issued_raw = license_data.get("issued_at_utc")
    expires_raw = license_data.get("expires_at_utc")
    if not client_id or not expires_raw:
        raise BuildError("Cliente/licencia incompleto")
    if not all(char.isalnum() or char in "-_" for char in client_id) or len(client_id) > 64:
        raise BuildError("client_id contiene caracteres no permitidos")
    issued = parse_utc(issued_raw, "issued_at_utc") if issued_raw else datetime.now(timezone.utc)
    expires = parse_utc(expires_raw, "expires_at_utc")
    if expires <= issued:
        raise BuildError("La expiración debe ser posterior a la emisión")
    return client_id, license_id, issued, expires


def _issue_client_envelope(client: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    license_private, license_public = _ensure_keys("license")
    client_id, license_id, issued, expires = _client_claims(client)
    envelope = issue_license(
        private_key_path=license_private,
        client_id=client_id,
        license_id=license_id,
        issued_at_utc=issued,
        expires_at_utc=expires,
    )
    return envelope, license_public


def _copy_public_key_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def export_client_license_bundle(
    client: dict[str, Any],
    *,
    destination: str | os.PathLike[str] | None = None,
) -> dict[str, str]:
    """Emite la licencia firmada y su clave pública sin compilar el instalador.

    Sin ``destination`` se guarda en ``clientes/<CLIENT_ID>``. Cuando se elige
    una carpeta externa, el contenido queda listo para copiar sobre la carpeta
    instalada: ``licencia.key`` y ``assets/license_public_key.pem``.
    """

    client_id, _, _, _ = _client_claims(client)
    bundle_root = Path(destination) if destination is not None else CLIENTS / client_id
    bundle_root.mkdir(parents=True, exist_ok=True)
    envelope, public_key = _issue_client_envelope(client)
    license_path = bundle_root / "licencia.key"
    public_key_path = bundle_root / "assets" / "license_public_key.pem"
    write_json_atomic(license_path, envelope, backup=True)
    _copy_public_key_atomic(public_key, public_key_path)
    return {
        "license_path": str(license_path.resolve()),
        "public_key_path": str(public_key_path.resolve()),
    }


def _prepare_work(client: dict[str, Any], build_root: Path) -> Path:
    work = build_root / "work"
    _copy_template(work)
    envelope, license_public = _issue_client_envelope(client)
    _, update_public = _ensure_keys("update")
    assets = work / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    _copy_public_key_atomic(license_public, assets / "license_public_key.pem")
    _copy_public_key_atomic(update_public, assets / "update_public_key.pem")
    write_json_atomic(work / "licencia.key", envelope, backup=False)
    return work


def _write_inno(build_root: Path, app_dir: Path, out_dir: Path, client_id: str, *, icon: bool) -> Path:
    output_name = f"LectorCedulasDMS_Setup_{client_id}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"
    icon_line = f'SetupIconFile="{app_dir / "assets" / "DMS_icono_circulo_i.ico"}"' if icon else "; SetupIconFile omitido por error 110 confirmado"
    script = build_root / "LectorCedulasDMS.iss"
    script.write_text(
        f'''#define MyAppName "{PRODUCT_NAME}"
#define MyAppVersion "{VERSION}"
#define MyAppPublisher "Digital Management Systems"
#define MyAppExeName "LectorCedulasDMS.exe"

[Setup]
AppId={{{{DMS-LECTOR-CEDULAS}}}}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
DefaultDirName={{autopf}}\\DMS\\LectorCedulasDMS
DefaultGroupName={{#MyAppName}}
OutputDir="{out_dir}"
OutputBaseFilename={output_name}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
{icon_line}
UninstallDisplayIcon={{app}}\\{{#MyAppExeName}}

[Files]
Source: "{app_dir}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"
Name: "{{group}}\\Configurar lector"; Filename: "{{app}}\\crear_configuracion.exe"

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Description: "Ejecutar {{#MyAppName}}"; Flags: nowait postinstall skipifsilent
''',
        encoding="utf-8",
    )
    return script


def _compile_inno(build_root: Path, app_dir: Path, out_dir: Path, client_id: str, log: Path) -> Path:
    iscc = _iscc()
    script = _write_inno(build_root, app_dir, out_dir, client_id, icon=True)
    result = subprocess.run([iscc, str(script)], cwd=build_root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    with log.open("a", encoding="utf-8") as handle:
        handle.write(result.stdout + result.stderr)
    if result.returncode:
        combined = (result.stdout + result.stderr).casefold()
        if "endupdateresource failed" in combined and "110" in combined:
            script = _write_inno(build_root, app_dir, out_dir, client_id, icon=False)
            _run([iscc, str(script)], cwd=build_root, log=log)
        else:
            raise BuildError(f"Inno Setup falló con código {result.returncode}; revise {log}")
    candidates = sorted(out_dir.glob(f"LectorCedulasDMS_Setup_{client_id}_*.exe"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        raise BuildError("No se encontró el Setup.exe generado")
    return candidates[-1]


def _generate_sbom(work: Path, destination: Path, log: Path) -> None:
    tool = shutil.which("cyclonedx-py")
    if not tool:
        raise BuildError("cyclonedx-py no está instalado; no se generó SBOM")
    _run([tool, "environment", "--output-format", "JSON", "--output-file", str(destination)], cwd=work, log=log)


def make_installer_zip(client: dict[str, Any], out_dir: str) -> str:
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    client_id = str(client.get("client_id") or "CLIENTE")
    export_client_license_bundle(client)
    build_root = CLIENTS / "_build" / f"{client_id}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"
    build_root.mkdir(parents=True, exist_ok=True)
    log = build_root / "build.log"
    work = _prepare_work(client, build_root)
    main_exe = _build_exe(work, "main.py", "LectorCedulasDMS", log)
    config_exe = _build_exe(work, "crear_configuracion.py", "crear_configuracion", log)
    updater_work = build_root / "updater_work"
    shutil.copytree(work, updater_work, dirs_exist_ok=True)
    shutil.copy2(ROOT / "tools" / "updater.py", updater_work / "updater.py")
    updater_exe = _build_exe(updater_work, "updater.py", "DMSUpdater", log, console=True)

    app_dir = build_root / "app"
    app_dir.mkdir()
    shutil.copy2(main_exe, app_dir / "LectorCedulasDMS.exe")
    shutil.copy2(config_exe, app_dir / "crear_configuracion.exe")
    shutil.copy2(updater_exe, app_dir / "DMSUpdater.exe")
    shutil.copytree(work / "assets", app_dir / "assets", dirs_exist_ok=True)
    shutil.copytree(work / "configs", app_dir / "configs", dirs_exist_ok=True)
    shutil.copy2(work / "licencia.key", app_dir / "licencia.key")
    _generate_sbom(work, app_dir / "sbom.cdx.json", log)
    setup = _compile_inno(build_root, app_dir, destination, client_id, log)
    shutil.copy2(log, destination / f"{setup.stem}.build.log")
    return str(setup)


def make_update_zip(version: str, out_dir: str) -> str:
    if version != VERSION:
        raise BuildError(f"La versión solicitada {version} no coincide con la fuente única {VERSION}")
    destination = Path(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    build_root = CLIENTS / "_build" / f"UPDATE_{VERSION}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"
    build_root.mkdir(parents=True, exist_ok=True)
    log = build_root / "build.log"
    dummy = {
        "client_id": "UPDATE-BUILD",
        "license": {
            "license_id": "LIC-UPDATE-BUILD",
            "issued_at_utc": "2026-01-01T00:00:00Z",
            "expires_at_utc": "2099-01-01T00:00:00Z",
        },
    }
    work = _prepare_work(dummy, build_root)
    main_exe = _build_exe(work, "main.py", "LectorCedulasDMS", log)
    config_exe = _build_exe(work, "crear_configuracion.py", "crear_configuracion", log)
    updater_work = build_root / "updater_work"
    shutil.copytree(work, updater_work, dirs_exist_ok=True)
    shutil.copy2(ROOT / "tools" / "updater.py", updater_work / "updater.py")
    updater_exe = _build_exe(updater_work, "updater.py", "DMSUpdater", log, console=True)

    package = build_root / "package"
    payload = package / "payload"
    payload.mkdir(parents=True)
    shutil.copy2(main_exe, payload / "LectorCedulasDMS.exe")
    shutil.copy2(config_exe, payload / "crear_configuracion.exe")
    shutil.copytree(work / "assets", payload / "assets", dirs_exist_ok=True)
    shutil.copy2(updater_exe, package / "DMSUpdater.exe")
    files = [path.relative_to(payload).as_posix() for path in payload.rglob("*") if path.is_file()]
    manifest_payload = {
        "schema_version": UPDATE_MANIFEST_SCHEMA_VERSION,
        "product": PRODUCT_ID,
        "version": VERSION,
        "built_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": build_file_entries(payload, files),
    }
    update_private, _ = _ensure_keys("update")
    write_json_atomic(package / "manifest.json", sign_manifest(manifest_payload, update_private), backup=False)
    _generate_sbom(work, package / "sbom.cdx.json", log)
    archive = shutil.make_archive(str(destination / f"LectorCedulasDMS_Update_{VERSION}"), "zip", package)
    shutil.copy2(log, destination / f"LectorCedulasDMS_Update_{VERSION}.build.log")
    return archive
