from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .atomic_io import AtomicJsonError, read_json, write_json_atomic
from .version import LICENSE_SCHEMA_VERSION, PRODUCT_ID


class LicenseError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise LicenseError(f"{field_name} ausente")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise LicenseError(f"{field_name} no tiene formato ISO-8601 válido") from exc
    if parsed.tzinfo is None:
        raise LicenseError(f"{field_name} debe incluir zona horaria UTC")
    parsed = parsed.astimezone(timezone.utc)
    return parsed


def iso_z(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("datetime sin zona horaria")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def payload_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class LicenseClaims:
    schema_version: int
    product: str
    client_id: str
    license_id: str
    issued_at_utc: datetime
    expires_at_utc: datetime
    installation_id: str | None


class LicenseVerifier:
    def __init__(
        self,
        *,
        public_key_path: str | os.PathLike[str],
        license_path: str | os.PathLike[str],
        state_path: str | os.PathLike[str],
        clock: Callable[[], datetime] = utc_now,
        rollback_tolerance: timedelta = timedelta(minutes=5),
    ):
        self.public_key_path = Path(public_key_path)
        self.license_path = Path(license_path)
        self.state_path = Path(state_path)
        self.clock = clock
        self.rollback_tolerance = rollback_tolerance

    def _load_public_key(self) -> Ed25519PublicKey:
        try:
            raw = self.public_key_path.read_bytes()
            key = serialization.load_pem_public_key(raw)
        except Exception as exc:
            raise LicenseError("No se pudo cargar la clave pública de licencia") from exc
        if not isinstance(key, Ed25519PublicKey):
            raise LicenseError("La clave pública no es Ed25519")
        return key

    def _load_envelope(self) -> dict[str, Any]:
        try:
            envelope = read_json(self.license_path, required=True)
        except AtomicJsonError as exc:
            raise LicenseError(str(exc)) from exc
        if not isinstance(envelope, dict):
            raise LicenseError("La licencia debe ser un objeto JSON")
        if "payload" not in envelope or "signature" not in envelope:
            if "licencia" in envelope or "expira" in envelope:
                raise LicenseError(
                    "La licencia usa el formato antiguo y debe renovarse desde el dashboard seguro"
                )
            raise LicenseError("La licencia no contiene payload y firma")
        return envelope

    def _validate_payload(self, payload: Any, installation_id: str | None) -> LicenseClaims:
        if not isinstance(payload, dict):
            raise LicenseError("payload inválido")
        required = {
            "schema_version",
            "product",
            "client_id",
            "license_id",
            "issued_at_utc",
            "expires_at_utc",
        }
        missing = sorted(required - set(payload))
        if missing:
            raise LicenseError("Campos de licencia ausentes: " + ", ".join(missing))
        schema_version = payload.get("schema_version")
        if schema_version != LICENSE_SCHEMA_VERSION:
            raise LicenseError(f"Versión de licencia no soportada: {schema_version}")
        product = str(payload.get("product") or "")
        if product != PRODUCT_ID:
            raise LicenseError("La licencia pertenece a otro producto")
        client_id = str(payload.get("client_id") or "").strip()
        license_id = str(payload.get("license_id") or "").strip()
        if not client_id or len(client_id) > 128 or not license_id or len(license_id) > 128:
            raise LicenseError("client_id o license_id inválido")
        issued = parse_utc(payload.get("issued_at_utc"), "issued_at_utc")
        expires = parse_utc(payload.get("expires_at_utc"), "expires_at_utc")
        if expires <= issued:
            raise LicenseError("La expiración debe ser posterior a la emisión")
        bound_installation = payload.get("installation_id")
        if bound_installation is not None:
            bound_installation = str(bound_installation).strip()
            if not installation_id:
                raise LicenseError("La licencia requiere identificación de instalación")
            if bound_installation != installation_id:
                raise LicenseError("La licencia pertenece a otra instalación")
        return LicenseClaims(
            schema_version=schema_version,
            product=product,
            client_id=client_id,
            license_id=license_id,
            issued_at_utc=issued,
            expires_at_utc=expires,
            installation_id=bound_installation,
        )

    def _check_clock_rollback(self, now: datetime, digest: str) -> None:
        try:
            state = read_json(self.state_path, default={}) or {}
        except AtomicJsonError:
            state = {}
        if not isinstance(state, dict):
            state = {}
        previous_hash = state.get("license_sha256")
        previous_seen_raw = state.get("last_seen_utc")
        if previous_hash == digest and previous_seen_raw:
            try:
                previous_seen = parse_utc(previous_seen_raw, "last_seen_utc")
            except LicenseError:
                previous_seen = None
            if previous_seen and now + self.rollback_tolerance < previous_seen:
                raise LicenseError("El reloj del sistema retrocedió de forma no permitida")
        write_json_atomic(
            self.state_path,
            {"license_sha256": digest, "last_seen_utc": iso_z(now)},
            backup=False,
        )

    def verify(self, *, installation_id: str | None = None) -> LicenseClaims:
        envelope = self._load_envelope()
        payload = envelope.get("payload")
        signature_text = envelope.get("signature")
        if not isinstance(signature_text, str):
            raise LicenseError("Firma ausente")
        try:
            signature = base64.b64decode(signature_text, validate=True)
        except Exception as exc:
            raise LicenseError("Firma no codificada correctamente") from exc
        public_key = self._load_public_key()
        try:
            public_key.verify(signature, canonical_payload(payload))
        except InvalidSignature as exc:
            raise LicenseError("La firma de la licencia es inválida") from exc
        claims = self._validate_payload(payload, installation_id)
        now = self.clock()
        if now.tzinfo is None:
            raise LicenseError("El reloj interno debe devolver una fecha con zona horaria")
        now = now.astimezone(timezone.utc)
        if now < claims.issued_at_utc - timedelta(minutes=5):
            raise LicenseError("La licencia todavía no es válida; revise el reloj de Windows")
        if now >= claims.expires_at_utc:
            raise LicenseError("La licencia ha expirado")
        digest = payload_digest(payload)
        self._check_clock_rollback(now, digest)
        return claims


def generate_keypair(private_key_path: str | os.PathLike[str], public_key_path: str | os.PathLike[str]) -> None:
    private_path = Path(private_key_path)
    public_path = Path(public_key_path)
    if private_path.exists():
        raise FileExistsError(f"La clave privada ya existe: {private_path}")
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_path.write_bytes(private_bytes)
    public_path.write_bytes(public_bytes)
    try:
        os.chmod(private_path, 0o600)
    except OSError:
        pass


def issue_license(
    *,
    private_key_path: str | os.PathLike[str],
    client_id: str,
    license_id: str,
    issued_at_utc: datetime,
    expires_at_utc: datetime,
    installation_id: str | None = None,
) -> dict[str, Any]:
    private_key_raw = Path(private_key_path).read_bytes()
    key = serialization.load_pem_private_key(private_key_raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise LicenseError("La clave privada no es Ed25519")
    payload: dict[str, Any] = {
        "schema_version": LICENSE_SCHEMA_VERSION,
        "product": PRODUCT_ID,
        "client_id": str(client_id).strip(),
        "license_id": str(license_id).strip(),
        "issued_at_utc": iso_z(issued_at_utc),
        "expires_at_utc": iso_z(expires_at_utc),
    }
    if installation_id:
        payload["installation_id"] = str(installation_id).strip()
    signature = key.sign(canonical_payload(payload))
    return {
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
