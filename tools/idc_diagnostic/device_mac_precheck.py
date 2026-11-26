"""QA21: consistencia de DeviceMac con la clave del MSO aún no confiable.

No autentica emisor ni identidad. No imprime o persiste material criptográfico.
Solo verifica una forma estricta COSE_Mac0 / HMAC 256/256 de ISO 18013-5.
"""
from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping

from .signed_items_lab import _decode

DOC = "org.iso.18013.5.1.mDL"


def empty_mac_precheck():
    return {
        "mdl_mac_cose_parts_valid": False,
        "mdl_mac_protected_headers_decodable": False,
        "mdl_mac_alg5_protected": False,
        "mdl_mac_alg5_unprotected": False,
        "mdl_mac_detached_payload": False,
        "mdl_mac_tag_is_bytes": False,
        "mdl_mac_tag_32_bytes": False,
        "mdl_mac_tag_empty": False,
        "mdl_mac_consistency_checked": False,
        "mdl_mac_matches_untrusted_mso_key": False,
    }


def _parts(obj, tag):
    import cbor2

    if isinstance(obj, cbor2.CBORTag):
        if obj.tag != tag:
            return None
        obj = obj.value
    return obj if isinstance(obj, (list, tuple)) and len(obj) == 4 else None


def inspect_mac_consistency(response, material):
    report = empty_mac_precheck()
    try:
        import cbor2
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF

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
        device = doc.get("deviceSigned")
        auth = device.get("deviceAuth") if isinstance(device, Mapping) else None
        parts = _parts(auth.get("deviceMac"), 17) if isinstance(auth, Mapping) else None
        if parts is None:
            return report
        report["mdl_mac_cose_parts_valid"] = True
        protected, unprotected, payload, tag = parts
        report["mdl_mac_detached_payload"] = payload is None
        report["mdl_mac_tag_is_bytes"] = isinstance(tag, bytes)
        report["mdl_mac_tag_32_bytes"] = isinstance(tag, bytes) and len(tag) == 32
        report["mdl_mac_tag_empty"] = isinstance(tag, bytes) and not tag
        report["mdl_mac_alg5_unprotected"] = (
            isinstance(unprotected, Mapping) and type(unprotected.get(1)) is int
            and unprotected[1] == 5
        )
        headers = _decode(protected) if protected else {}
        if not isinstance(headers, Mapping):
            return report
        report["mdl_mac_protected_headers_decodable"] = True
        report["mdl_mac_alg5_protected"] = type(headers.get(1)) is int and headers[1] == 5
        if not (
            report["mdl_mac_alg5_protected"] and set(headers) == {1}
            and isinstance(unprotected, Mapping) and not unprotected
            and payload is None and report["mdl_mac_tag_32_bytes"]
            and set(auth) == {"deviceMac"}
        ):
            return report
        issuer = doc.get("issuerSigned")
        sign1 = _parts(issuer.get("issuerAuth"), 18) if isinstance(issuer, Mapping) else None
        if sign1 is None or not isinstance(sign1[2], bytes):
            return report
        wrapped = _decode(sign1[2])
        if not isinstance(wrapped, cbor2.CBORTag) or wrapped.tag != 24:
            return report
        mso = _decode(wrapped.value)
        if not isinstance(mso, Mapping) or mso.get("docType") != DOC or mso.get("version") != "1.0":
            return report
        info = mso.get("deviceKeyInfo")
        key = info.get("deviceKey") if isinstance(info, Mapping) else None
        if not isinstance(key, Mapping) or not (
            type(key.get(1)) is int and key[1] == 2
            and type(key.get(-1)) is int and key[-1] == 1
            and -4 not in key and isinstance(key.get(-2), bytes) and len(key[-2]) == 32
            and isinstance(key.get(-3), bytes) and len(key[-3]) == 32
        ):
            return report
        pub = ec.EllipticCurvePublicNumbers(
            int.from_bytes(key[-2], "big"), int.from_bytes(key[-3], "big"), ec.SECP256R1()
        ).public_key()
        spaces = device.get("nameSpaces")
        if not isinstance(spaces, cbor2.CBORTag) or spaces.tag != 24:
            return report
        # Este ensayo no autentica datos adicionales del dispositivo.
        if _decode(spaces.value) != {}:
            return report
        transcript_bytes = material.session_transcript
        transcript_tag = _decode(transcript_bytes)
        if not isinstance(transcript_tag, cbor2.CBORTag) or transcript_tag.tag != 24:
            return report
        transcript = _decode(transcript_tag.value)
        if not isinstance(transcript, (list, tuple)) or len(transcript) != 3:
            return report
        # Usar exactamente los bytes del transcript generado por el lector.
        authentication = (
            b"\x84" + cbor2.dumps("DeviceAuthentication") + transcript_tag.value
            + cbor2.dumps(DOC) + cbor2.dumps(spaces)
        )
        detached = cbor2.dumps(cbor2.CBORTag(24, authentication))
        shared = material.reader_key.exchange(ec.ECDH(), pub)
        emac = HKDF(
            algorithm=hashes.SHA256(), length=32,
            salt=hashlib.sha256(transcript_bytes).digest(), info=b"EMacKey",
        ).derive(shared)
        expected = hmac.digest(emac, cbor2.dumps(["MAC0", protected, b"", detached]), "sha256")
        report["mdl_mac_consistency_checked"] = True
        report["mdl_mac_matches_untrusted_mso_key"] = hmac.compare_digest(expected, tag)
    except Exception:
        return report
    return report
