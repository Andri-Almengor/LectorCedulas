"""QA17: prueba voluntaria de interoperabilidad con ISO Photo ID.

Hipótesis pública, NO perfil confirmado de IDC. Solo pide país emisor;
no extrae valores, no verifica identidad ni guarda respuestas.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from .ble_link_probe import _get_transport_options, _load_cbor
from .ble_session_lab import _ble_exchange
from .capture import capture_serial
from .mdoc_core import (
    SessionCipherState, build_device_request, build_session_establishment, prepare_reader_session,
)

DOC_TYPE = "org.iso.23220.photoid.1"
NAMESPACE = "org.iso.23220.1"
ELEMENT = "issuing_country"


def candidate_request() -> bytes:
    return build_device_request(doc_type=DOC_TYPE, requested_namespaces={NAMESPACE: (ELEMENT,)})


def _report():
    return {
        "purpose": "public_photoid_candidate_probe_only",
        "schema_version": 1,
        "candidate_is_confirmed_idc_profile": False,
        "consent_confirmed": False,
        "encrypted_reply_authenticated": False,
        "response_status_code": None,
        "response_document_count_category": "unavailable",
        "response_document_errors_present": False,
        "response_document_error_category": "unavailable",
        "issuer_signature_verified": False,
        "device_auth_verified": False,
        "iaca_trust_anchor_validated": False,
        "verified_identity": False,
        "idc_verification_available": False,
        "status": "consent_and_candidate_permission_required",
    }


def probe_candidate(raw_qr: bytes, *, consent: bool, allow_candidate: bool, scan_seconds: float = 30):
    report = _report()
    if not consent or not allow_candidate:
        return report
    report["consent_confirmed"] = True
    if not 3 <= scan_seconds <= 30:
        report["status"] = "invalid_timeout"
        return report
    try:
        _, _, _, service_uuid = _get_transport_options(raw_qr, decode_cbor=_load_cbor)
        if service_uuid is None:
            report["status"] = "directed_ble_service_unavailable"
            return report
        material = prepare_reader_session(raw_qr)
        cipher = SessionCipherState(material)
        packet = build_session_establishment(material, cipher, candidate_request())
        result = asyncio.run(asyncio.wait_for(
            _ble_exchange(service_uuid, scan_seconds, packet, cipher),
            timeout=scan_seconds + 37,
        ))
        if not isinstance(result, dict):
            report["status"] = "invalid_probe_result"
            return report
        if result.get("encrypted_reply_authenticated") is not True:
            report["status"] = "no_authenticated_candidate_response"
            return report
        report["encrypted_reply_authenticated"] = True
        count = result.get("response_document_count_category")
        if count in ("unavailable", "absent", "none", "one", "multiple", "invalid"):
            report["response_document_count_category"] = count
        code = result.get("response_status_code")
        if type(code) is int and 0 <= code <= 255:
            report["response_status_code"] = code
        report["response_document_errors_present"] = result.get("response_document_errors_present") is True
        category = result.get("response_document_error_category")
        if category in ("absent", "data_not_returned", "nonzero_document_error", "malformed", "unavailable"):
            report["response_document_error_category"] = category
        if code == 0 and count == "one" and result.get("response_structure_acceptable") is True:
            report["status"] = "candidate_document_observed_not_verified"
        elif count in ("absent", "none") and report["response_document_errors_present"]:
            report["status"] = "candidate_document_error_not_verified"
        else:
            report["status"] = "candidate_response_inconclusive"
    except ImportError:
        report["status"] = "optional_dependency_missing"
    except TimeoutError:
        report["status"] = "candidate_probe_timeout"
    except Exception:
        report["status"] = "candidate_probe_failed"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Hipótesis ISO Photo ID: solicita solo país emisor.")
    parser.add_argument("--port", required=True)
    parser.add_argument("--consent", action="store_true")
    parser.add_argument("--allow-photoid-candidate", action="store_true")
    parser.add_argument("--ble-scan-seconds", type=float, default=30)
    args = parser.parse_args(argv)
    if not args.consent or not args.allow_photoid_candidate or not 3 <= args.ble_scan_seconds <= 30:
        parser.error("Requiere consentimiento, permiso explícito y tiempo BLE entre 3 y 30 segundos.")
    try:
        print("Escanee su QR nuevo. Autorice solo país emisor en el teléfono; cancele si pide otros datos.")
        raw = capture_serial(args.port, baudrate=9600, timeout_seconds=25)
        report = probe_candidate(raw, consent=True, allow_candidate=True, scan_seconds=args.ble_scan_seconds)
    except Exception:
        report = _report()
        report["status"] = "capture_failed"
    print(json.dumps(report, sort_keys=True))
    return 0 if report["encrypted_reply_authenticated"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
