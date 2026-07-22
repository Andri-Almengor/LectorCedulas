from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from packaging.version import InvalidVersion, Version

from .version import PRODUCT_ID, UPDATE_MANIFEST_SCHEMA_VERSION


class ManifestError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ManifestFile:
    path: str
    sha256: str
    size: int


def canonical_manifest_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def safe_relative_path(value: str) -> str:
    candidate = PurePosixPath(str(value).replace("\\", "/"))
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ManifestError(f"Ruta no permitida en manifest: {value}")
    if ":" in candidate.parts[0]:
        raise ManifestError(f"Ruta no permitida en manifest: {value}")
    return candidate.as_posix()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_file_entries(root: str | os.PathLike[str], paths: Iterable[str]) -> list[dict[str, Any]]:
    base = Path(root)
    entries: list[dict[str, Any]] = []
    for raw in sorted(set(paths)):
        relative = safe_relative_path(raw)
        target = base / Path(relative)
        if not target.is_file():
            raise ManifestError(f"Archivo de payload ausente: {relative}")
        entries.append({"path": relative, "sha256": sha256_file(target), "size": target.stat().st_size})
    return entries


def sign_manifest(payload: dict[str, Any], private_key_path: str | os.PathLike[str]) -> dict[str, Any]:
    key = serialization.load_pem_private_key(Path(private_key_path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ManifestError("La clave privada de update no es Ed25519")
    signature = key.sign(canonical_manifest_payload(payload))
    return {"payload": payload, "signature": base64.b64encode(signature).decode("ascii")}


def _load_public_key(path: str | os.PathLike[str]) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key(Path(path).read_bytes())
    except Exception as exc:
        raise ManifestError("No se pudo cargar la clave pública de updates") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise ManifestError("La clave pública de updates no es Ed25519")
    return key


def verify_manifest(
    envelope: dict[str, Any],
    *,
    public_key_path: str | os.PathLike[str],
    current_version: str,
    allow_downgrade: bool = False,
) -> tuple[str, tuple[ManifestFile, ...]]:
    if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
        raise ManifestError("Manifest inválido")
    payload = envelope["payload"]
    signature_text = envelope.get("signature")
    if not isinstance(signature_text, str):
        raise ManifestError("Manifest sin firma")
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except Exception as exc:
        raise ManifestError("Firma de manifest mal codificada") from exc
    try:
        _load_public_key(public_key_path).verify(signature, canonical_manifest_payload(payload))
    except InvalidSignature as exc:
        raise ManifestError("Firma de manifest inválida") from exc
    if payload.get("schema_version") != UPDATE_MANIFEST_SCHEMA_VERSION:
        raise ManifestError("Versión de manifest no soportada")
    if payload.get("product") != PRODUCT_ID:
        raise ManifestError("El update pertenece a otro producto")
    version_text = str(payload.get("version") or "")
    try:
        new_version = Version(version_text)
        installed_version = Version(current_version)
    except InvalidVersion as exc:
        raise ManifestError("Versión inválida en manifest") from exc
    if not allow_downgrade and new_version < installed_version:
        raise ManifestError("Downgrade bloqueado")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ManifestError("Manifest sin archivos")
    seen: set[str] = set()
    files: list[ManifestFile] = []
    for item in raw_files:
        if not isinstance(item, dict):
            raise ManifestError("Entrada de archivo inválida")
        relative = safe_relative_path(item.get("path", ""))
        if relative in seen:
            raise ManifestError(f"Archivo duplicado en manifest: {relative}")
        seen.add(relative)
        sha = str(item.get("sha256") or "").casefold()
        size = item.get("size")
        if len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha):
            raise ManifestError(f"SHA-256 inválido: {relative}")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ManifestError(f"Tamaño inválido: {relative}")
        files.append(ManifestFile(relative, sha, size))
    return version_text, tuple(files)
