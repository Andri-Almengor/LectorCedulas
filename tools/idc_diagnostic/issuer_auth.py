"""Prevalidación *parcial* de IssuerAuth ISO/IEC 18013-5.

Este módulo no declara identidades auténticas. Requiere explícitamente un
certificado raíz IACA confiable proporcionado por el integrador; NO lo descarga.
Solo admite la cadena directa IACA -> Document Signer y COSE ES256.
Sin DeviceAuth, digests completos, CRL/OCSP y evaluación de política de confianza
NO puede utilizarse para registro de personas.
"""
from __future__ import annotations

import hashlib
import hmac
import io
from datetime import datetime, timezone
from typing import Any


_MAX_AUTH_BYTES = 65536
_MAX_CERT_BYTES = 16384
_MDL_DS_EKU = "1.0.18013.5.1.2"
_GENERAL_MDOC_DS_EKU = "1.3.6.1.4.1.61546.0"


class IssuerAuthError(ValueError):
    """Resultado categórico sin contenido personal ni material de sesión."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _cbor_full(raw: bytes) -> Any:
    import cbor2

    stream = io.BytesIO(raw)
    item = cbor2.CBORDecoder(stream).decode()
    if stream.read(1):
        raise IssuerAuthError("trailing_cbor_data")
    return item


def _parse_time(value: Any) -> datetime:
    from datetime import datetime

    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise IssuerAuthError("invalid_mso_time")
        return value.astimezone(timezone.utc)
    if isinstance(value, str) and len(value) <= 40:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise IssuerAuthError("invalid_mso_time") from exc
        if dt.tzinfo is None:
            raise IssuerAuthError("invalid_mso_time")
        return dt.astimezone(timezone.utc)
    raise IssuerAuthError("invalid_mso_time")


def _require_direct_chain(der_leaf: bytes, der_iaca: bytes, when: datetime) -> Any:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtensionOID, NameOID

    if not 1 <= len(der_leaf) <= _MAX_CERT_BYTES or not 1 <= len(der_iaca) <= _MAX_CERT_BYTES:
        raise IssuerAuthError("invalid_certificate")
    try:
        iaca = x509.load_der_x509_certificate(der_iaca)
        signer = x509.load_der_x509_certificate(der_leaf)
        root_public = iaca.public_key()
        leaf_public = signer.public_key()
        if not isinstance(root_public, ec.EllipticCurvePublicKey) or not isinstance(
            leaf_public, ec.EllipticCurvePublicKey
        ):
            raise IssuerAuthError("unsupported_certificate_key")
        if not isinstance(leaf_public.curve, ec.SECP256R1):
            raise IssuerAuthError("unsupported_certificate_key")
        if iaca.issuer != iaca.subject or signer.issuer != iaca.subject:
            raise IssuerAuthError("invalid_certificate_chain")

        root_public.verify(iaca.signature, iaca.tbs_certificate_bytes, ec.ECDSA(iaca.signature_hash_algorithm))
        root_public.verify(signer.signature, signer.tbs_certificate_bytes, ec.ECDSA(signer.signature_hash_algorithm))

        root_basic = iaca.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
        root_usage = iaca.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
        leaf_basic = signer.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
        leaf_usage = signer.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
        leaf_eku = signer.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE).value

        if not root_basic.ca or not root_usage.key_cert_sign:
            raise IssuerAuthError("untrusted_iaca_profile")
        if leaf_basic.ca or not leaf_usage.digital_signature or leaf_usage.key_cert_sign:
            raise IssuerAuthError("invalid_document_signer_profile")
        acceptable_eku = {_MDL_DS_EKU, _GENERAL_MDOC_DS_EKU}
        if not any(oid.dotted_string in acceptable_eku for oid in leaf_eku):
            raise IssuerAuthError("invalid_document_signer_profile")

        if not (
            iaca.not_valid_before_utc <= when <= iaca.not_valid_after_utc
            and signer.not_valid_before_utc <= when <= signer.not_valid_after_utc
        ):
            raise IssuerAuthError("expired_or_future_certificate")
        if signer.not_valid_before_utc < iaca.not_valid_before_utc or (
            signer.not_valid_after_utc > iaca.not_valid_after_utc
        ):
            raise IssuerAuthError("invalid_signer_validity")

        root_country = iaca.subject.get_attributes_for_oid(NameOID.COUNTRY_NAME)
        leaf_country = signer.subject.get_attributes_for_oid(NameOID.COUNTRY_NAME)
        if len(root_country) != 1 or len(leaf_country) != 1 or (
            root_country[0].value != leaf_country[0].value
        ):
            raise IssuerAuthError("issuer_country_mismatch")
    except IssuerAuthError:
        raise
    except Exception as exc:
        raise IssuerAuthError("invalid_certificate_chain") from exc
    return signer


def verify_issuer_auth_signature(
    issuer_auth_bytes: bytes,
    *,
    trusted_iaca_der: bytes | None,
    expected_doc_type: str,
    when: datetime | None = None,
) -> dict[str, object]:
    """Comprueba firma, anclaje directo IACA, docType y ventana del MSO.

    *No* valida digest de todos los atributos, vinculación de dispositivo,
    revocación ni identidad. Nunca devuelve datos, certificados o docType.
    """
    report: dict[str, object] = {
        "schema_version": 1,
        "purpose": "issuer_auth_crypto_precheck_only",
        "trusted_iaca_chain_valid": False,
        "issuer_signature_valid": False,
        "mso_doc_type_valid": False,
        "mso_time_valid": False,
        "all_issuer_item_digests_verified": False,
        "device_auth_verified": False,
        "certificate_revocation_checked": False,
        "verified_identity": False,
        "idc_verification_available": False,
        "status": "not_started",
    }
    if trusted_iaca_der is None:
        report["status"] = "trusted_iaca_required"
        return report
    if not isinstance(trusted_iaca_der, bytes) or not isinstance(issuer_auth_bytes, bytes):
        report["status"] = "invalid_input"
        return report
    if not 1 <= len(issuer_auth_bytes) <= _MAX_AUTH_BYTES:
        report["status"] = "invalid_input"
        return report
    if not isinstance(expected_doc_type, str) or not 1 <= len(expected_doc_type) <= 128:
        report["status"] = "invalid_document_type"
        return report
    current = when or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        report["status"] = "invalid_reference_time"
        return report
    current = current.astimezone(timezone.utc)

    try:
        import cbor2
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        from cryptography.hazmat.primitives import hashes

        sign1 = _cbor_full(issuer_auth_bytes)
        if isinstance(sign1, cbor2.CBORTag):
            if sign1.tag != 18:
                raise IssuerAuthError("invalid_cose_sign1")
            sign1 = sign1.value
        if not isinstance(sign1, list) or len(sign1) != 4:
            raise IssuerAuthError("invalid_cose_sign1")
        protected_raw, unprotected, payload, signature = sign1
        if not isinstance(protected_raw, bytes) or not isinstance(unprotected, dict):
            raise IssuerAuthError("invalid_cose_sign1")
        if not isinstance(payload, bytes) or not isinstance(signature, bytes) or len(signature) != 64:
            raise IssuerAuthError("invalid_cose_sign1")
        protected = _cbor_full(protected_raw) if protected_raw else {}
        if not isinstance(protected, dict) or protected.get(1) != -7 or 1 in unprotected:
            raise IssuerAuthError("unsupported_cose_algorithm")
        x5chain = unprotected.get(33)
        if isinstance(x5chain, bytes):
            der_signer = x5chain
        elif isinstance(x5chain, list) and len(x5chain) == 1 and isinstance(x5chain[0], bytes):
            der_signer = x5chain[0]
        else:
            raise IssuerAuthError("unsupported_certificate_chain")

        cert = _require_direct_chain(der_signer, trusted_iaca_der, current)
        report["trusted_iaca_chain_valid"] = True

        signed_bytes = cbor2.dumps(["Signature1", protected_raw, b"", payload])
        raw_r = int.from_bytes(signature[:32], "big")
        raw_s = int.from_bytes(signature[32:], "big")
        der_signature = utils.encode_dss_signature(raw_r, raw_s)
        try:
            cert.public_key().verify(der_signature, signed_bytes, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature as exc:
            raise IssuerAuthError("invalid_issuer_signature") from exc
        report["issuer_signature_valid"] = True

        outer = _cbor_full(payload)
        if not isinstance(outer, cbor2.CBORTag) or outer.tag != 24 or not isinstance(outer.value, bytes):
            raise IssuerAuthError("invalid_mso")
        mso = _cbor_full(outer.value)
        if not isinstance(mso, dict) or mso.get("version") != "1.0":
            raise IssuerAuthError("invalid_mso")
        if mso.get("docType") != expected_doc_type:
            raise IssuerAuthError("doc_type_mismatch")
        report["mso_doc_type_valid"] = True
        validity = mso.get("validityInfo")
        if not isinstance(validity, dict):
            raise IssuerAuthError("invalid_mso")
        signed = _parse_time(validity.get("signed"))
        valid_from = _parse_time(validity.get("validFrom"))
        valid_until = _parse_time(validity.get("validUntil"))
        if not (signed <= valid_from < valid_until and valid_from <= current < valid_until):
            raise IssuerAuthError("invalid_mso_validity")
        report["mso_time_valid"] = True
        report["status"] = "issuer_auth_partial_precheck_passed_not_identity"
    except IssuerAuthError as exc:
        report["status"] = exc.code
    except (ImportError, ModuleNotFoundError):
        report["status"] = "optional_crypto_dependency_missing"
    except Exception:
        # Evitar incluir mensajes de librerías que pudieran contener datos.
        report["status"] = "invalid_or_unsupported_issuer_auth"
    return report


def issuer_signed_item_digest_matches(tagged_item: Any, signed_digest: bytes) -> bool:
    """Primitiva de comparación SHA-256 para ItemBytes sintéticos.

    No equivale a verificar todos los elementos del documento.
    """
    import cbor2

    if not isinstance(tagged_item, cbor2.CBORTag) or tagged_item.tag != 24:
        return False
    if not isinstance(tagged_item.value, bytes) or not 1 <= len(tagged_item.value) <= 16384:
        return False
    if not isinstance(signed_digest, bytes) or len(signed_digest) != 32:
        return False
    try:
        decoded = _cbor_full(tagged_item.value)
    except Exception:
        return False
    if not isinstance(decoded, dict) or not (
        isinstance(decoded.get("digestID"), int)
        and isinstance(decoded.get("elementIdentifier"), str)
    ):
        return False
    calculated = hashlib.sha256(cbor2.dumps(tagged_item)).digest()
    return hmac.compare_digest(calculated, signed_digest)
