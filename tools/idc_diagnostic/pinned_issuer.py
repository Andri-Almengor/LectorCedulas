"""QA24: partial direct issuer validation with externally supplied IACA.

A matching pin proves only that the supplied certificate matches the supplied
hash. The operator must authenticate the source independently. No trust-on-first
use, automatic trust, export of presented certs, or final identity approval.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from datetime import datetime, timezone

from .issuer_auth import verify_issuer_auth_signature

DOC = "org.iso.18013.5.1.mDL"
MAX_CERT = 16384


def check_anchor(der, pin, *, when=None):
    if not isinstance(der, bytes) or not 1 <= len(der) <= MAX_CERT:
        return False
    if not isinstance(pin, str) or not re.fullmatch(r"[0-9a-f]{64}", pin):
        return False
    if not hmac.compare_digest(hashlib.sha256(der).hexdigest(), pin):
        return False
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import Encoding
        from cryptography.x509.oid import ExtensionOID

        cert = x509.load_der_x509_certificate(der)
        now = when if when is not None else datetime.now(timezone.utc)
        key = cert.public_key()
        if not (
            cert.public_bytes(Encoding.DER) == der
            and cert.subject == cert.issuer
            and isinstance(key, ec.EllipticCurvePublicKey)
            and cert.not_valid_before_utc <= now <= cert.not_valid_after_utc
            and cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value.ca
            and cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value.key_cert_sign
        ):
            return False
        key.verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm))
        return True
    except Exception:
        return False


def empty_pinned_precheck():
    return {
        "mdl_pinned_anchor_precheck_passed": False,
        "mdl_pinned_issuer_chain_precheck_passed": False,
        "mdl_pinned_issuer_signature_precheck_passed": False,
        "mdl_pinned_issuer_mso_precheck_passed": False,
    }


def inspect_pinned_issuer(response, der, pin, *, when=None):
    report = empty_pinned_precheck()
    if not check_anchor(der, pin, when=when):
        return report
    report["mdl_pinned_anchor_precheck_passed"] = True
    try:
        import cbor2

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
        auth = issuer.get("issuerAuth") if isinstance(issuer, Mapping) else None
        if auth is None:
            return report
        result = verify_issuer_auth_signature(
            cbor2.dumps(auth), trusted_iaca_der=der, expected_doc_type=DOC, when=when
        )
        report["mdl_pinned_issuer_chain_precheck_passed"] = result["trusted_iaca_chain_valid"] is True
        report["mdl_pinned_issuer_signature_precheck_passed"] = result["issuer_signature_valid"] is True
        report["mdl_pinned_issuer_mso_precheck_passed"] = (
            result["status"] == "issuer_auth_partial_precheck_passed_not_identity"
        )
    except Exception:
        return report
    return report
