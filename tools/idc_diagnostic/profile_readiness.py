"""QA15: preparación del perfil IDC, no autorización ni validación real.

El integrador debe obtener el esquema y el hash del ancla por canales
autenticados independientes. Este módulo no los descubre ni los descarga.
Nunca declara una identidad válida ni abre una sesión BLE.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re

MAX_PROFILE = 8192
MAX_CERT = 16384
_TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:/-]{0,127}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {"doc_type", "namespace", "name_element", "number_element", "reader_auth"}
_FIELDS_TOP = {"schema_version", *_FIELDS}


class ProfileError(ValueError):
    pass


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError("duplicate_profile_key")
        result[key] = value
    return result


def _parse_profile(raw):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_PROFILE:
        raise ProfileError("invalid_profile_size")
    config = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    if not isinstance(config, dict) or set(config) != _FIELDS_TOP:
        raise ProfileError("invalid_profile_fields")
    if type(config["schema_version"]) is not int or config["schema_version"] != 1:
        raise ProfileError("unsupported_profile_version")
    for field in _FIELDS - {"reader_auth"}:
        value = config[field]
        if not isinstance(value, str) or not _TOKEN.fullmatch(value):
            raise ProfileError("invalid_profile_identifier")
        if value.lower().startswith(("org.example", "example", "test_", "placeholder")):
            raise ProfileError("synthetic_or_placeholder_profile")
    if config["name_element"] == config["number_element"]:
        raise ProfileError("duplicate_profile_element")
    if config["reader_auth"] not in ("required", "not_required", "unknown"):
        raise ProfileError("invalid_reader_auth_policy")
    return config


def inspect_profile_readiness(
    profile_json: bytes | None,
    *,
    candidate_iaca_der: bytes | None = None,
    independently_pinned_sha256: str | None = None,
) -> dict[str, object]:
    """Comprueba estructura y coincidencia con un hash suministrado externamente.

    No prueba que el hash venga del TSE ni que el perfil corresponda a IDC.
    No usa el certificado de una respuesta como fuente de confianza.
    """
    report: dict[str, object] = {
        "schema_version": 1,
        "purpose": "idc_profile_readiness_only",
        "profile_structure_valid": False,
        "reader_auth_policy_known": False,
        "anchor_fingerprint_matches": False,
        "anchor_ca_shape_valid": False,
        "profile_authenticity_verified": False,
        "iaca_trust_anchor_validated": False,
        "verified_identity": False,
        "idc_verification_available": False,
        "status": "profile_required",
    }
    if profile_json is None:
        return report
    try:
        config = _parse_profile(profile_json)
        report["profile_structure_valid"] = True
        if config["reader_auth"] == "unknown":
            report["status"] = "reader_auth_policy_required"
            return report
        report["reader_auth_policy_known"] = True
        if independently_pinned_sha256 is None:
            report["status"] = "independent_anchor_pin_required"
            return report
        if not isinstance(independently_pinned_sha256, str) or not _HASH.fullmatch(
            independently_pinned_sha256
        ):
            raise ProfileError("invalid_anchor_pin")
        if not isinstance(candidate_iaca_der, bytes) or not 1 <= len(candidate_iaca_der) <= MAX_CERT:
            raise ProfileError("candidate_anchor_required")
        if not hmac.compare_digest(
            hashlib.sha256(candidate_iaca_der).hexdigest(), independently_pinned_sha256
        ):
            raise ProfileError("anchor_fingerprint_mismatch")
        report["anchor_fingerprint_matches"] = True

        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtensionOID

        cert = x509.load_der_x509_certificate(candidate_iaca_der)
        basic = cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
        usage = cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
        key = cert.public_key()
        if not basic.ca or not usage.key_cert_sign or cert.subject != cert.issuer:
            raise ProfileError("invalid_anchor_ca_shape")
        if not isinstance(key, ec.EllipticCurvePublicKey):
            raise ProfileError("unsupported_anchor_key")
        key.verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm))
        report["anchor_ca_shape_valid"] = True
        report["status"] = "candidate_profile_structurally_ready_not_verified"
    except ProfileError as exc:
        report["status"] = str(exc)
    except ImportError:
        report["status"] = "optional_crypto_dependency_missing"
    except Exception:
        report["status"] = "invalid_or_unsupported_profile_material"
    return report
