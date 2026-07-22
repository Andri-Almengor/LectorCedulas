from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from assets.runtime.hardened.update_manifest import ManifestError, build_file_entries, sign_manifest, verify_manifest
from assets.runtime.hardened.version import PRODUCT_ID, UPDATE_MANIFEST_SCHEMA_VERSION


def keys(tmp_path):
    private = Ed25519PrivateKey.generate()
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"
    private_path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public_path.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return private_path, public_path


def envelope(tmp_path, version="4.0.1"):
    payload_root = tmp_path / "payload"
    payload_root.mkdir(parents=True)
    (payload_root / "LectorCedulasDMS.exe").write_bytes(b"X" * 2048)
    private, public = keys(tmp_path)
    payload = {"schema_version": UPDATE_MANIFEST_SCHEMA_VERSION, "product": PRODUCT_ID, "version": version, "built_at_utc": "2026-07-22T20:00:00Z", "files": build_file_entries(payload_root, ["LectorCedulasDMS.exe"])}
    return sign_manifest(payload, private), public


def test_signed_manifest_and_downgrade_protection(tmp_path):
    env, public = envelope(tmp_path)
    version, files = verify_manifest(env, public_key_path=public, current_version="4.0.0")
    assert version == "4.0.1"
    assert files[0].path == "LectorCedulasDMS.exe"
    old, public2 = envelope(tmp_path / "old", version="3.9.9")
    with pytest.raises(ManifestError, match="Downgrade"):
        verify_manifest(old, public_key_path=public2, current_version="4.0.0")


def test_manifest_tamper_and_path_traversal_rejected(tmp_path):
    env, public = envelope(tmp_path)
    env["payload"]["version"] = "9.0.0"
    with pytest.raises(ManifestError, match="[Ff]irma"):
        verify_manifest(env, public_key_path=public, current_version="4.0.0")
