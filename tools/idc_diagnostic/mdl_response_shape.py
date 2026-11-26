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
    }


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
    device = doc.get("deviceSigned")
    if isinstance(device, Mapping):
        report["mdl_device_signed_present"] = True
        auth = device.get("deviceAuth")
        if isinstance(auth, Mapping):
            report["mdl_device_signature_present"] = auth.get("deviceSignature") is not None
            report["mdl_device_mac_present"] = auth.get("deviceMac") is not None
    issuer = doc.get("issuerSigned")
    if not isinstance(issuer, Mapping):
        return report
    report["mdl_issuer_auth_present"] = issuer.get("issuerAuth") is not None
    spaces = issuer.get("nameSpaces")
    if not isinstance(spaces, Mapping) or NS not in spaces:
        return report
    report["mdl_requested_namespace_present"] = True
    report["mdl_additional_issuer_items_present"] = len(spaces) != 1
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
