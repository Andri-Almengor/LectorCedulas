from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from assets.runtime.hardened.atomic_io import write_json_atomic
from assets.runtime.hardened.license_service import (
    LicenseError,
    LicenseVerifier,
    ensure_keypair,
    generate_keypair,
    issue_license,
)

NOW = datetime(2026, 7, 22, 20, 0, tzinfo=timezone.utc)


def setup_license(tmp_path, **overrides):
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    license_path = tmp_path / "licencia.key"
    state = tmp_path / "state.json"
    generate_keypair(private, public)
    params = {
        "private_key_path": private,
        "client_id": "CLIENTE-PRUEBA",
        "license_id": "LIC-PRUEBA-001",
        "issued_at_utc": NOW - timedelta(days=1),
        "expires_at_utc": NOW + timedelta(days=30),
    }
    params.update(overrides)
    envelope = issue_license(**params)
    write_json_atomic(license_path, envelope, backup=False)
    verifier = LicenseVerifier(
        public_key_path=public,
        license_path=license_path,
        state_path=state,
        clock=lambda: NOW,
    )
    return verifier, envelope, license_path, state, private, public


def test_valid_license(tmp_path):
    verifier, *_ = setup_license(tmp_path)
    assert verifier.verify().client_id == "CLIENTE-PRUEBA"


def test_expired_license(tmp_path):
    verifier, *_ = setup_license(
        tmp_path,
        expires_at_utc=NOW - timedelta(seconds=1),
    )
    with pytest.raises(LicenseError, match="expirado"):
        verifier.verify()


def test_signature_modified(tmp_path):
    verifier, envelope, path, *_ = setup_license(tmp_path)
    envelope["signature"] = "A" + envelope["signature"][1:]
    write_json_atomic(path, envelope, backup=False)
    with pytest.raises(LicenseError, match="firma"):
        verifier.verify()


def test_payload_modified(tmp_path):
    verifier, envelope, path, *_ = setup_license(tmp_path)
    envelope["payload"]["client_id"] = "OTRO"
    write_json_atomic(path, envelope, backup=False)
    with pytest.raises(LicenseError, match="firma"):
        verifier.verify()


def test_malformed_or_naive_date_rejected(tmp_path):
    verifier, envelope, path, *_ = setup_license(tmp_path)
    envelope["payload"]["expires_at_utc"] = "2026-08-01T00:00:00"
    write_json_atomic(path, envelope, backup=False)
    with pytest.raises(LicenseError):
        verifier.verify()


def test_old_cache_does_not_override_renewed_license(tmp_path):
    verifier, _, path, state, private, public = setup_license(tmp_path)
    verifier.verify()
    renewed = issue_license(
        private_key_path=private,
        client_id="CLIENTE-PRUEBA",
        license_id="LIC-RENOVADA",
        issued_at_utc=NOW,
        expires_at_utc=NOW + timedelta(days=365),
    )
    write_json_atomic(path, renewed, backup=False)
    new_verifier = LicenseVerifier(
        public_key_path=public,
        license_path=path,
        state_path=state,
        clock=lambda: NOW,
    )
    assert new_verifier.verify().license_id == "LIC-RENOVADA"


def test_reinstall_without_state_is_valid(tmp_path):
    verifier, *_ = setup_license(tmp_path)
    verifier.state_path.unlink(missing_ok=True)
    assert verifier.verify().license_id == "LIC-PRUEBA-001"


def test_legacy_license_requires_migration(tmp_path):
    verifier, _, path, *_ = setup_license(tmp_path)
    write_json_atomic(
        path,
        {"licencia": "legacy", "expira": "2027-01-01"},
        backup=False,
    )
    with pytest.raises(LicenseError, match="formato antiguo"):
        verifier.verify()


def test_timezone_change_is_normalized(tmp_path):
    verifier, *_ = setup_license(tmp_path)
    verifier.clock = lambda: NOW.astimezone(timezone(timedelta(hours=-6)))
    assert verifier.verify().license_id == "LIC-PRUEBA-001"


def test_clock_rollback_is_rejected(tmp_path):
    verifier, *_ = setup_license(tmp_path)
    verifier.verify()
    verifier.clock = lambda: NOW - timedelta(hours=1)
    with pytest.raises(LicenseError, match="reloj"):
        verifier.verify()


def test_installation_binding(tmp_path):
    verifier, *_ = setup_license(tmp_path, installation_id="INSTALL-A")
    assert verifier.verify(installation_id="INSTALL-A").installation_id == "INSTALL-A"
    with pytest.raises(LicenseError, match="otra instalación"):
        verifier.verify(installation_id="INSTALL-B")


def test_ensure_keypair_restores_missing_public_without_changing_private(tmp_path):
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    ensure_keypair(private, public)
    original_private = private.read_bytes()
    original_public = public.read_bytes()

    public.unlink()
    ensure_keypair(private, public)

    assert private.read_bytes() == original_private
    assert public.read_bytes() == original_public


def test_ensure_keypair_repairs_mismatched_public(tmp_path):
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    other_private = tmp_path / "other-private.pem"
    other_public = tmp_path / "other-public.pem"
    generate_keypair(private, public)
    expected_public = public.read_bytes()
    generate_keypair(other_private, other_public)
    public.write_bytes(other_public.read_bytes())

    ensure_keypair(private, public)

    assert public.read_bytes() == expected_public


@pytest.mark.parametrize("field", ["client_id", "license_id"])
def test_issue_license_rejects_empty_identifiers(tmp_path, field):
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    generate_keypair(private, public)
    params = {
        "private_key_path": private,
        "client_id": "CLIENTE",
        "license_id": "LICENCIA",
        "issued_at_utc": NOW,
        "expires_at_utc": NOW + timedelta(days=1),
    }
    params[field] = ""

    with pytest.raises(LicenseError, match=field):
        issue_license(**params)


def test_issue_license_rejects_naive_or_reversed_dates(tmp_path):
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    generate_keypair(private, public)

    with pytest.raises(LicenseError, match="zona horaria"):
        issue_license(
            private_key_path=private,
            client_id="CLIENTE",
            license_id="LICENCIA",
            issued_at_utc=datetime(2026, 1, 1),
            expires_at_utc=NOW,
        )

    with pytest.raises(LicenseError, match="posterior"):
        issue_license(
            private_key_path=private,
            client_id="CLIENTE",
            license_id="LICENCIA",
            issued_at_utc=NOW,
            expires_at_utc=NOW,
        )


def test_atomic_keypair_creation_leaves_no_temp_files(tmp_path):
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    ensure_keypair(private, public)
    assert private.is_file()
    assert public.is_file()
    assert not list(tmp_path.glob("*.tmp"))
