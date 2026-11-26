"""Diagnóstico categórico de DeviceResponse: sin atributos ni datos personales.

Esta información solo se genera DESPUÉS de autenticar la respuesta AES-GCM.
La inspección no verifica IssuerAuth, certificados IACA ni DeviceAuth; por lo
tanto jamás informa que una identidad sea auténtica.
"""
from __future__ import annotations

from typing import Any


def classify_device_response_structure(value: Any) -> dict[str, object]:
    """Resume forma, estado y número aproximado de documentos, nunca contenidos.

    La salida contiene únicamente booleanos, categorías fijas y códigos
    pequeños de estado. No expone docTypes, namespaces, certificados o errores
    arbitrarios recibidos del dispositivo.
    """
    report: dict[str, object] = {
        "response_status_code": None,
        "response_status_category": "unavailable",
        "response_version_supported": False,
        "response_document_count_category": "unavailable",
        "response_document_errors_present": False,
        "response_unexpected_document_present": False,
        "response_structure_acceptable": False,
    }
    if not isinstance(value, dict):
        return report

    report["response_version_supported"] = value.get("version") == "1.0"

    status = value.get("status")
    if type(status) is not int or not 0 <= status <= 255:
        report["response_status_category"] = "invalid_or_missing"
        return report
    report["response_status_code"] = status
    report["response_status_category"] = "ok" if status == 0 else "nonzero"

    documents = value.get("documents")
    if documents is None:
        report["response_document_count_category"] = "absent"
    elif not isinstance(documents, list):
        report["response_document_count_category"] = "invalid"
        return report
    elif not documents:
        report["response_document_count_category"] = "none"
    elif len(documents) == 1:
        report["response_document_count_category"] = "one"
        report["response_unexpected_document_present"] = True
    else:
        report["response_document_count_category"] = "multiple"
        report["response_unexpected_document_present"] = True

    errors = value.get("documentErrors")
    report["response_document_errors_present"] = (
        isinstance(errors, (list, tuple, dict)) and bool(errors)
    )

    # El contrato aquí solo es diagnóstico. Nunca se declara documento auténtico.
    report["response_structure_acceptable"] = (
        report["response_version_supported"] is True
        and report["response_document_count_category"] != "invalid"
    )
    return report
