"""QA19: inspección de forma de la respuesta mDL, sin divulgación de valores.

Solo permite indicadores fijos. No acredita la firma, la cadena de confianza,
la autorización del lector ni la identidad del titular.
"""
from __future__ import annotations

from collections.abc import Mapping

from .signed_items_lab import _decode

DOC = "org.iso.18013.5.1.mDL"
NS = "org.iso.18013.5.1"
ELEMENT = "issuing_country"


def empty_mdl_shape():
    return {
        "mdl_returned_doc_type_matches": False,
        "mdl_requested_namespace_present": False,
        "mdl_issuing_country_present": False,
        "mdl_issuing_country_shape_valid": False,
        "mdl_additional_issuer_items_present": False,
        "mdl_issuer_auth_present": False,
        "mdl_device_signed_present": False,
        "mdl_device_signature_present": False,
        "mdl_device_mac_present": False,
        "mdl_requested_item_structure_valid": False,
        "mdl_issuer_namespaces_present": False,
        "mdl_issuer_namespaces_empty": False,
        "mdl_issuer_other_namespace_present": False,
        "mdl_issuer_requested_namespace_empty": False,
        "mdl_device_namespaces_present": False,
        "mdl_device_namespaces_empty": False,
        "mdl_device_requested_namespace_present": False,
        "mdl_device_other_namespace_present": False,
        "mdl_document_item_errors_present": False,
        "mdl_requested_country_error_present": False,
        "mdl_requested_country_error_data_not_returned": False,
        "mdl_requested_country_error_nonzero": False,
        "mdl_mso_decodable": False,
        "mdl_mso_doc_type_matches": False,
        "mdl_mso_requested_digest_namespace_present": False,
        "mdl_mso_other_digest_namespace_present": False,
        "mdl_mso_device_key_p256_shape": False,
        "mdl_mac_hmac256_shape": False,
    }


def _cose_parts(value, tag_number):
    import cbor2

    if isinstance(value, cbor2.CBORTag):
        if value.tag != tag_number:
            return None
        value = value.value
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return value
    return None


def _inspect_mso_shape(auth, report):
    # Payload sin verificar; no utilizar para tomar decisiones de identidad.
    try:
        import cbor2

        parts = _cose_parts(auth, 18)
        if parts is None or not isinstance(parts[2], bytes):
            return
        tagged = _decode(parts[2])
        if not isinstance(tagged, cbor2.CBORTag) or tagged.tag != 24:
            return
        mso = _decode(tagged.value)
        if not isinstance(mso, Mapping):
            return
        report["mdl_mso_decodable"] = True
        report["mdl_mso_doc_type_matches"] = mso.get("docType") == DOC
        digests = mso.get("valueDigests")
        if isinstance(digests, Mapping):
            report["mdl_mso_requested_digest_namespace_present"] = NS in digests
            report["mdl_mso_other_digest_namespace_present"] = any(key != NS for key in digests)
        info = mso.get("deviceKeyInfo")
        key = info.get("deviceKey") if isinstance(info, Mapping) else None
        if isinstance(key, Mapping):
            report["mdl_mso_device_key_p256_shape"] = (
                type(key.get(1)) is int and key.get(1) == 2
                and type(key.get(-1)) is int and key.get(-1) == 1
                and isinstance(key.get(-2), bytes) and len(key[-2]) == 32
                and isinstance(key.get(-3), bytes) and len(key[-3]) == 32
            )
    except Exception:
        return


def _inspect_device_shape(device, report):
    try:
        import cbor2

        spaces = device.get("nameSpaces")
        if isinstance(spaces, cbor2.CBORTag) and spaces.tag == 24:
            spaces = _decode(spaces.value)
            if isinstance(spaces, Mapping):
                report["mdl_device_namespaces_present"] = True
                report["mdl_device_namespaces_empty"] = not spaces
                report["mdl_device_requested_namespace_present"] = NS in spaces
                report["mdl_device_other_namespace_present"] = any(key != NS for key in spaces)
    except Exception:
        pass
    try:
        auth = device.get("deviceAuth")
        parts = _cose_parts(auth.get("deviceMac"), 17) if isinstance(auth, Mapping) else None
        if parts is None:
            return
        protected, unprotected, payload, tag = parts
        headers = _decode(protected)
        report["mdl_mac_hmac256_shape"] = (
            isinstance(headers, Mapping) and type(headers.get(1)) is int and headers[1] == 5
            and isinstance(unprotected, Mapping) and 1 not in unprotected
            and payload is None and isinstance(tag, bytes) and len(tag) == 32
        )
    except Exception:
        return


def inspect_mdl_shape(response):
    report = empty_mdl_shape()
    if not isinstance(response, Mapping):
        return report
    documents = response.get("documents")
    if (
        response.get("version") != "1.0" or type(response.get("status")) is not int
        or response["status"] != 0 or not isinstance(documents, list) or len(documents) != 1
    ):
        return report
    doc = documents[0]
    if not isinstance(doc, Mapping) or doc.get("docType") != DOC:
        return report
    report["mdl_returned_doc_type_matches"] = True
    item_errors = doc.get("errors")
    report["mdl_document_item_errors_present"] = isinstance(item_errors, Mapping) and bool(item_errors)
    ns_errors = item_errors.get(NS) if isinstance(item_errors, Mapping) else None
    if isinstance(ns_errors, Mapping) and ELEMENT in ns_errors:
        report["mdl_requested_country_error_present"] = True
        code = ns_errors[ELEMENT]
        report["mdl_requested_country_error_data_not_returned"] = type(code) is int and code == 0
        report["mdl_requested_country_error_nonzero"] = type(code) is int and code != 0
    device = doc.get("deviceSigned")
    if isinstance(device, Mapping):
        report["mdl_device_signed_present"] = True
        _inspect_device_shape(device, report)
        auth = device.get("deviceAuth")
        if isinstance(auth, Mapping):
            report["mdl_device_signature_present"] = auth.get("deviceSignature") is not None
            report["mdl_device_mac_present"] = auth.get("deviceMac") is not None
    issuer = doc.get("issuerSigned")
    if not isinstance(issuer, Mapping):
        return report
    report["mdl_issuer_auth_present"] = issuer.get("issuerAuth") is not None
    _inspect_mso_shape(issuer.get("issuerAuth"), report)
    spaces = issuer.get("nameSpaces")
    if not isinstance(spaces, Mapping):
        return report
    report["mdl_issuer_namespaces_present"] = True
    report["mdl_issuer_namespaces_empty"] = not spaces
    report["mdl_issuer_other_namespace_present"] = any(key != NS for key in spaces)
    report["mdl_additional_issuer_items_present"] = any(
        key != NS and isinstance(items, (list, tuple)) and bool(items)
        for key, items in spaces.items()
    )
    if NS not in spaces:
        return report
    report["mdl_requested_namespace_present"] = True
    report["mdl_issuer_requested_namespace_empty"] = spaces[NS] in ([], ())
    items = spaces[NS]
    if not isinstance(items, (list, tuple)) or not 1 <= len(items) <= 64:
        return report
    report["mdl_additional_issuer_items_present"] |= len(items) > 1
    try:
        import cbor2

        seen = set()
        matching = 0
        for tagged in items:
            if not isinstance(tagged, cbor2.CBORTag) or tagged.tag != 24:
                return report
            if not isinstance(tagged.value, bytes) or len(tagged.value) > 16384:
                return report
            item = _decode(tagged.value)
            if not isinstance(item, Mapping) or set(item) != {
                "digestID", "random", "elementIdentifier", "elementValue"
            }:
                return report
            digest_id = item["digestID"]
            name = item["elementIdentifier"]
            if (
                type(digest_id) is not int or not 0 <= digest_id <= 0xFFFFFFFF
                or digest_id in seen or not isinstance(name, str)
                or not isinstance(item["random"], bytes) or len(item["random"]) < 16
            ):
                return report
            seen.add(digest_id)
            if name == ELEMENT:
                matching += 1
                report["mdl_issuing_country_present"] = True
                # Solo forma, no se retorna ni registra el valor.
                value = item["elementValue"]
                report["mdl_issuing_country_shape_valid"] = (
                    isinstance(value, str) and len(value) == 2
                    and value.isascii() and value.isalpha() and value.isupper()
                )
            else:
                report["mdl_additional_issuer_items_present"] = True
        report["mdl_requested_item_structure_valid"] = (
            matching == 1 and report["mdl_issuing_country_shape_valid"]
        )
    except Exception:
        return report
    return report
