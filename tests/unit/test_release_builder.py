from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from template.assets.runtime.hardened.license_service import LicenseVerifier
from tools import release_builder


def client(expires_in_days: int = 30) -> dict:
    issued = datetime.now(timezone.utc)
    return {
        "client_id": "CLIENTE_PRUEBA",
        "name": "Cliente Prueba",
        "license": {
            "license_id": "LIC-CLIENTE-PRUEBA",
            "issued_at_utc": issued.isoformat().replace("+00:00", "Z"),
            "expires_at_utc": (issued + timedelta(days=expires_in_days)).isoformat().replace("+00:00", "Z"),
        },
    }


def test_export_client_license_bundle_creates_signed_new_format(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(release_builder, "CLIENTS", tmp_path / "clientes")
    monkeypatch.setattr(release_builder, "_secret_root", lambda: tmp_path / "secrets")

    result = release_builder.export_client_license_bundle(client())
    license_path = Path(result["license_path"])
    public_key_path = Path(result["public_key_path"])

    envelope = json.loads(license_path.read_text(encoding="utf-8"))
    assert set(envelope) == {"payload", "signature"}
    assert envelope["payload"]["client_id"] == "CLIENTE_PRUEBA"
    assert public_key_path == license_path.parent / "assets" / "license_public_key.pem"
    assert not list(license_path.parent.rglob("*private*"))

    claims = LicenseVerifier(
        public_key_path=public_key_path,
        license_path=license_path,
        state_path=tmp_path / "state.json",
    ).verify()
    assert claims.license_id == "LIC-CLIENTE-PRUEBA"


def test_renewed_bundle_replaces_license_with_same_public_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(release_builder, "CLIENTS", tmp_path / "clientes")
    monkeypatch.setattr(release_builder, "_secret_root", lambda: tmp_path / "secrets")

    first = release_builder.export_client_license_bundle(client(10))
    first_envelope = json.loads(Path(first["license_path"]).read_text(encoding="utf-8"))
    public_before = Path(first["public_key_path"]).read_bytes()

    second = release_builder.export_client_license_bundle(client(60))
    second_envelope = json.loads(Path(second["license_path"]).read_text(encoding="utf-8"))

    assert first["license_path"] == second["license_path"]
    assert first_envelope["signature"] != second_envelope["signature"]
    assert Path(second["public_key_path"]).read_bytes() == public_before
    LicenseVerifier(
        public_key_path=second["public_key_path"],
        license_path=second["license_path"],
        state_path=tmp_path / "renewed-state.json",
    ).verify()


def test_client_id_cannot_escape_clients_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(release_builder, "CLIENTS", tmp_path / "clientes")
    monkeypatch.setattr(release_builder, "_secret_root", lambda: tmp_path / "secrets")
    malicious = client()
    malicious["client_id"] = "../../escape"

    try:
        release_builder.export_client_license_bundle(malicious)
    except release_builder.BuildError as exc:
        assert "caracteres no permitidos" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Se aceptó un client_id inseguro")
