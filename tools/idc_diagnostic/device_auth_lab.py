"""QA14: verificación parcial de DeviceSignature con credenciales ficticias.

Solo perfil QA13, sin conexión a un teléfono. No verifica revocación, política
de confianza de IDC ni autorización real. No devuelve claves o atributos.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from .signed_items_lab import DOC, DigestError, _decode, _tag24, precheck_synthetic_signed_items


def _device_key(mso):
    from cryptography.hazmat.primitives.asymmetric import ec

    info = mso.get("deviceKeyInfo")
    if not isinstance(info, Mapping) or set(info) != {"deviceKey"}:
        raise DigestError("unsupported_device_key_info")
    key = info["deviceKey"]
    if not isinstance(key, Mapping) or set(key) != {1, -1, -2, -3}:
        raise DigestError("invalid_device_key")
    if type(key[1]) is not int or key[1] != 2 or type(key[-1]) is not int or key[-1] != 1:
        raise DigestError("unsupported_device_key")
    x, y = key[-2], key[-3]
    if not isinstance(x, bytes) or not isinstance(y, bytes) or len(x) != 32 or len(y) != 32:
        raise DigestError("invalid_device_key_coordinates")
    try:
        return ec.EllipticCurvePublicNumbers(
            int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()
        ).public_key()
    except ValueError as exc:
        raise DigestError("invalid_device_key_point") from exc


def synthetic_transcript():
    """Genera un transcript ficticio nuevo para cada prueba, nunca reutilizar."""
    import secrets

    import cbor2

    return cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps([
        cbor2.CBORTag(24, cbor2.dumps({"lab_nonce": secrets.token_bytes(32)})),
        cbor2.CBORTag(24, cbor2.dumps({"lab_reader": secrets.token_bytes(32)})),
        None,
    ])))


def _device_authentication_bytes(transcript_bytes: bytes, namespaces_bytes: bytes) -> bytes:
    import cbor2

    transcript = _tag24(_decode(transcript_bytes))
    if not isinstance(transcript, (list, tuple)) or len(transcript) != 3 or transcript[2] is not None:
        raise DigestError("invalid_lab_transcript")
    for tagged, name in zip(transcript[:2], ("lab_nonce", "lab_reader")):
        inner = _tag24(tagged)
        if not isinstance(inner, Mapping) or set(inner) != {name}:
            raise DigestError("invalid_lab_transcript")
        if not isinstance(inner[name], bytes) or len(inner[name]) != 32:
            raise DigestError("invalid_lab_transcript")
    namespaces = _decode(namespaces_bytes)
    if _tag24(namespaces) != {}:
        raise DigestError("unexpected_device_namespaces")
    # DeviceAuthenticationBytes: tag 24 sobre el CBOR de la estructura ISO.
    # En laboratorio usamos únicamente codificación determinista emitida por nosotros.
    if cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps(transcript))) != transcript_bytes:
        raise DigestError("noncanonical_lab_transcript")
    if cbor2.dumps(namespaces) != namespaces_bytes:
        raise DigestError("noncanonical_device_namespaces")
    return cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps([
        "DeviceAuthentication", transcript, DOC, namespaces,
    ])))


def precheck_synthetic_device_auth(
    issuer_auth_bytes: bytes,
    *,
    trusted_iaca_der: bytes | None,
    items: tuple[bytes, ...],
    transcript_bytes: bytes,
    namespaces_bytes: bytes,
    device_signature_bytes: bytes,
    when: datetime | None = None,
) -> dict[str, object]:
    """Verifica DeviceSignature ES256 separada, con la clave del MSO firmado.

    transcript_bytes debe venir de la sesión actual del lector, nunca de una
    respuesta presentada por el titular. Solo QA, sin almacenamiento o BLE.
    """
    report: dict[str, object] = {
        "schema_version": 1,
        "purpose": "synthetic_device_auth_precheck_only",
        "issuer_auth_precheck_passed": False,
        "presented_item_digests_verified": False,
        "synthetic_device_signature_valid": False,
        "synthetic_session_binding_valid": False,
        "device_auth_verified": False,
        "certificate_revocation_checked": False,
        "verified_identity": False,
        "idc_verification_available": False,
        "status": "not_started",
    }
    try:
        import cbor2
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils

        prior = precheck_synthetic_signed_items(
            issuer_auth_bytes, trusted_iaca_der=trusted_iaca_der, items=items, when=when
        )
        for field in ("issuer_auth_precheck_passed", "presented_item_digests_verified"):
            report[field] = prior[field]
        if prior["status"] != "synthetic_signed_items_precheck_passed_not_identity":
            report["status"] = prior["status"]
            return report
        issuer = _decode(issuer_auth_bytes)
        if isinstance(issuer, cbor2.CBORTag):
            issuer = issuer.value
        mso = _tag24(_decode(issuer[2]))
        public = _device_key(mso)

        payload = _device_authentication_bytes(transcript_bytes, namespaces_bytes)
        sign1 = _decode(device_signature_bytes)
        if isinstance(sign1, cbor2.CBORTag):
            if sign1.tag != 18:
                raise DigestError("invalid_device_signature")
            sign1 = sign1.value
        if not isinstance(sign1, (tuple, list)) or len(sign1) != 4:
            raise DigestError("invalid_device_signature")
        protected, unprotected, attached, signature = sign1
        headers = _decode(protected)
        if not isinstance(headers, Mapping) or set(headers) != {1} or headers[1] != -7:
            raise DigestError("unsupported_device_algorithm")
        if not isinstance(unprotected, Mapping) or unprotected or attached is not None:
            raise DigestError("invalid_detached_device_signature")
        if not isinstance(signature, bytes) or len(signature) != 64:
            raise DigestError("invalid_device_signature")
        structure = cbor2.dumps(["Signature1", protected, b"", payload])
        der = utils.encode_dss_signature(
            int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
        )
        try:
            public.verify(der, structure, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature as exc:
            raise DigestError("invalid_device_signature") from exc
        report["synthetic_device_signature_valid"] = True
        report["synthetic_session_binding_valid"] = True
        report["status"] = "synthetic_device_auth_precheck_passed_not_identity"
    except DigestError as exc:
        report["status"] = str(exc)
    except ImportError:
        report["status"] = "optional_crypto_dependency_missing"
    except Exception:
        report["status"] = "invalid_or_unsupported_device_auth"
    return report
