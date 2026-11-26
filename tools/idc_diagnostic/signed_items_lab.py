"""QA13: prevalidación de digests de atributos sintéticos, sin BLE ni PII.

El resultado nunca acredita una identidad. Solo acepta el perfil de laboratorio.
Los bytes exactos de cada IssuerSignedItemBytes se suministran por separado;
no reconstruirlos a partir de un DeviceResponse decodificado.
"""
from __future__ import annotations

import hashlib
import hmac
import io
from collections.abc import Mapping
from datetime import datetime

from .issuer_auth import verify_issuer_auth_signature

DOC = "org.example.sample"
NAMESPACE = "org.example.person"
EXPECTED = frozenset({"sample_name", "sample_number"})
MAX_BYTES = 65536


class DigestError(ValueError):
    pass


def _decode(raw: bytes):
    import cbor2

    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES:
        raise DigestError("invalid_cbor_size")
    stream = io.BytesIO(raw)
    decoder = cbor2.CBORDecoder(
        stream, allow_duplicate_keys=False, allow_indefinite=False, max_depth=24, read_size=1
    )
    value = decoder.decode()
    if stream.read(1):
        raise DigestError("trailing_cbor_data")
    return value


def _tag24(value):
    import cbor2

    if not isinstance(value, cbor2.CBORTag) or value.tag != 24:
        raise DigestError("invalid_tag24")
    return _decode(value.value)


def _verify_items(mso: dict, items: tuple[bytes, ...]) -> None:
    if mso.get("digestAlgorithm") != "SHA-256":
        raise DigestError("unsupported_digest_algorithm")
    namespaces = mso.get("valueDigests")
    if not isinstance(namespaces, dict) or set(namespaces) != {NAMESPACE}:
        raise DigestError("unexpected_digest_namespace")
    digests = namespaces[NAMESPACE]
    if not isinstance(digests, dict) or not 2 <= len(digests) <= 16:
        raise DigestError("invalid_digest_table")
    for key, value in digests.items():
        if type(key) is not int or not 0 <= key <= 0xFFFFFFFF:
            raise DigestError("invalid_digest_id")
        if not isinstance(value, bytes) or len(value) != 32:
            raise DigestError("invalid_digest_length")
    if not isinstance(items, tuple) or len(items) != len(EXPECTED):
        raise DigestError("missing_or_extra_items")
    seen_ids = set()
    seen_names = set()
    for raw in items:
        if not isinstance(raw, bytes) or len(raw) > 16384:
            raise DigestError("invalid_item_size")
        item = _tag24(_decode(raw))
        if not isinstance(item, dict) or set(item) != {
            "digestID", "random", "elementIdentifier", "elementValue"
        }:
            raise DigestError("invalid_item_structure")
        digest_id = item["digestID"]
        name = item["elementIdentifier"]
        salt = item["random"]
        if type(digest_id) is not int or digest_id not in digests:
            raise DigestError("unknown_digest_id")
        if not isinstance(name, str) or name not in EXPECTED:
            raise DigestError("unexpected_element")
        if digest_id in seen_ids or name in seen_names:
            raise DigestError("duplicate_item")
        if not isinstance(salt, bytes) or not 16 <= len(salt) <= 128:
            raise DigestError("invalid_item_random")
        # Restricción del perfil de laboratorio; no aceptar valores reales.
        if item["elementValue"] != {"sample_name": "TEST_PERSON", "sample_number": "TEST_001"}[name]:
            raise DigestError("unexpected_synthetic_value")
        if not hmac.compare_digest(hashlib.sha256(raw).digest(), digests[digest_id]):
            raise DigestError("digest_mismatch")
        seen_ids.add(digest_id)
        seen_names.add(name)
    if seen_names != EXPECTED:
        raise DigestError("missing_expected_elements")


def precheck_synthetic_signed_items(
    issuer_auth_bytes: bytes,
    *,
    trusted_iaca_der: bytes | None,
    items: tuple[bytes, ...],
    when: datetime | None = None,
) -> dict[str, object]:
    """Comprueba firma parcial y los digests presentados del perfil ficticio.

    Sin DeviceAuth ni revocación. El ancla es externa, nunca tomada del documento.
    No devuelve elementos, certificados, hashes, ni datos de sesión.
    """
    report: dict[str, object] = {
        "schema_version": 1,
        "purpose": "synthetic_signed_items_precheck_only",
        "issuer_auth_precheck_passed": False,
        "presented_item_digests_verified": False,
        "device_auth_verified": False,
        "certificate_revocation_checked": False,
        "verified_identity": False,
        "idc_verification_available": False,
        "status": "not_started",
    }
    if trusted_iaca_der is None:
        report["status"] = "trusted_iaca_required"
        return report
    try:
        import cbor2

        sign1 = _decode(issuer_auth_bytes)
        if isinstance(sign1, cbor2.CBORTag):
            if sign1.tag != 18:
                raise DigestError("invalid_cose_sign1")
            sign1 = sign1.value
        if not isinstance(sign1, (list, tuple)) or len(sign1) != 4:
            raise DigestError("invalid_cose_sign1")
        protected = _decode(sign1[0])
        if not isinstance(protected, dict) or set(protected) != {1} or protected[1] != -7:
            raise DigestError("unsupported_protected_headers")
        if not isinstance(sign1[1], Mapping) or set(sign1[1]) != {33}:
            raise DigestError("unsupported_unprotected_headers")
        mso = _tag24(_decode(sign1[2]))
        if not isinstance(mso, dict) or mso.get("docType") != DOC:
            raise DigestError("unexpected_synthetic_document")
        auth = verify_issuer_auth_signature(
            issuer_auth_bytes, trusted_iaca_der=trusted_iaca_der, expected_doc_type=DOC, when=when
        )
        if auth["status"] != "issuer_auth_partial_precheck_passed_not_identity":
            report["status"] = auth["status"]
            return report
        report["issuer_auth_precheck_passed"] = True
        _verify_items(mso, items)
        report["presented_item_digests_verified"] = True
        report["status"] = "synthetic_signed_items_precheck_passed_not_identity"
    except DigestError as exc:
        report["status"] = str(exc)
    except ImportError:
        report["status"] = "optional_crypto_dependency_missing"
    except Exception:
        report["status"] = "invalid_or_unsupported_signed_items"
    return report
