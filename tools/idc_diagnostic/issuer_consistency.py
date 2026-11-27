"""QA23: consistencia de IssuerAuth con certificado presentado NO confiable.

No valida la cadena ni acredita al TSE. Sin datos personales, certificados
o claves en la salida. No usar para autorizar acceso ni registrar visitas.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone

from .issuer_auth import _parse_time
from .signed_items_lab import _decode

DOC = "org.iso.18013.5.1.mDL"


def empty_issuer_consistency():
    return {
        "mdl_issuer_cose_shape_valid": False,
        "mdl_issuer_es256_supported": False,
        "mdl_issuer_es384_supported": False,
        "mdl_issuer_es512_supported": False,
        "mdl_issuer_x5chain_present": False,
        "mdl_issuer_x5chain_multiple": False,
        "mdl_issuer_signer_cert_decodable": False,
        "mdl_issuer_signer_key_matches_alg": False,
        "mdl_issuer_signer_cert_current": False,
        "mdl_issuer_signature_consistency_checked": False,
        "mdl_issuer_signature_matches_untrusted_cert": False,
        "mdl_signed_mso_doc_type_matches": False,
        "mdl_signed_mso_time_window_current": False,
    }


def inspect_issuer_consistency(response, *, when=None):
    report = empty_issuer_consistency()
    try:
        import cbor2
        from cryptography import x509
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils

        now = when if when is not None else datetime.now(timezone.utc)
        if not isinstance(now, datetime) or now.tzinfo is None:
            return report
        if not isinstance(response, Mapping) or response.get("version") != "1.0":
            return report
        if type(response.get("status")) is not int or response["status"] != 0:
            return report
        docs = response.get("documents")
        if not isinstance(docs, list) or len(docs) != 1:
            return report
        doc = docs[0]
        if not isinstance(doc, Mapping) or doc.get("docType") != DOC:
            return report
        issuer = doc.get("issuerSigned")
        sign1 = issuer.get("issuerAuth") if isinstance(issuer, Mapping) else None
        if isinstance(sign1, cbor2.CBORTag):
            if sign1.tag != 18:
                return report
            sign1 = sign1.value
        if not isinstance(sign1, (list, tuple)) or len(sign1) != 4:
            return report
        protected, unprotected, payload, signature = sign1
        if not (
            isinstance(protected, bytes) and isinstance(unprotected, Mapping)
            and isinstance(payload, bytes) and 1 <= len(payload) <= 65536
            and isinstance(signature, bytes)
        ):
            return report
        headers = _decode(protected)
        if not isinstance(headers, Mapping) or set(headers) & set(unprotected):
            return report
        # Diagnostic support for the algorithm and x5chain only.
        if set(headers) - {1, 33} or set(unprotected) - {33}:
            return report
        report["mdl_issuer_cose_shape_valid"] = True
        alg = headers.get(1)
        if type(alg) is not int:
            return report
        algorithms = {
            -7: (ec.SECP256R1, hashes.SHA256, 32, "mdl_issuer_es256_supported"),
            -35: (ec.SECP384R1, hashes.SHA384, 48, "mdl_issuer_es384_supported"),
            -36: (ec.SECP521R1, hashes.SHA512, 66, "mdl_issuer_es512_supported"),
        }
        if alg not in algorithms:
            return report
        curve, digest, width, flag = algorithms[alg]
        report[flag] = True
        chain = headers.get(33, unprotected.get(33))
        if isinstance(chain, bytes):
            chain = [chain]
        if not isinstance(chain, (tuple, list)) or not 1 <= len(chain) <= 8:
            return report
        if not all(isinstance(cert, bytes) and 1 <= len(cert) <= 16384 for cert in chain):
            return report
        report["mdl_issuer_x5chain_present"] = True
        report["mdl_issuer_x5chain_multiple"] = len(chain) > 1
        cert = x509.load_der_x509_certificate(chain[0])
        report["mdl_issuer_signer_cert_decodable"] = True
        report["mdl_issuer_signer_cert_current"] = (
            cert.not_valid_before_utc <= now <= cert.not_valid_after_utc
        )
        key = cert.public_key()
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, curve):
            return report
        report["mdl_issuer_signer_key_matches_alg"] = True
        if len(signature) != 2 * width:
            return report
        der = utils.encode_dss_signature(
            int.from_bytes(signature[:width], "big"), int.from_bytes(signature[width:], "big")
        )
        structure = cbor2.dumps(["Signature1", protected, b"", payload])
        report["mdl_issuer_signature_consistency_checked"] = True
        try:
            key.verify(der, structure, ec.ECDSA(digest()))
        except InvalidSignature:
            return report
        report["mdl_issuer_signature_matches_untrusted_cert"] = True
        wrapped = _decode(payload)
        if not isinstance(wrapped, cbor2.CBORTag) or wrapped.tag != 24:
            return report
        mso = _decode(wrapped.value)
        if not isinstance(mso, Mapping) or mso.get("version") != "1.0":
            return report
        report["mdl_signed_mso_doc_type_matches"] = mso.get("docType") == DOC
        if not report["mdl_signed_mso_doc_type_matches"]:
            return report
        validity = mso.get("validityInfo")
        if not isinstance(validity, Mapping):
            return report
        signed = _parse_time(validity.get("signed"))
        start = _parse_time(validity.get("validFrom"))
        end = _parse_time(validity.get("validUntil"))
        report["mdl_signed_mso_time_window_current"] = signed <= start < end and start <= now < end
    except Exception:
        return report
    return report
