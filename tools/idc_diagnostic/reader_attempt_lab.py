"""QA15: consume una sesión ficticia una sola vez, incluso ante fallo.

No es transporte BLE ni un mecanismo persistente de replay. Cada intento
crea un transcript nuevo y solo el lector lo conserva.
"""
from __future__ import annotations

from threading import Lock

from .device_auth_lab import precheck_synthetic_device_auth, synthetic_transcript


class SyntheticReaderAttempt:
    def __init__(self):
        self._transcript = synthetic_transcript()
        self._lock = Lock()
        self._consumed = False

    def __repr__(self):
        return "<SyntheticReaderAttempt (redacted)>"

    def transcript_for_lab_holder(self) -> bytes:
        with self._lock:
            if self._consumed:
                raise RuntimeError("session_already_consumed")
            return self._transcript

    def verify(self, *, issuer_auth_bytes, trusted_iaca_der, items,
               namespaces_bytes, device_signature_bytes, when=None):
        with self._lock:
            if self._consumed:
                return {
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
                    "status": "session_already_consumed",
                }
            self._consumed = True
            transcript = self._transcript
            self._transcript = b""
        return precheck_synthetic_device_auth(
            issuer_auth_bytes,
            trusted_iaca_der=trusted_iaca_der,
            items=items,
            transcript_bytes=transcript,
            namespaces_bytes=namespaces_bytes,
            device_signature_bytes=device_signature_bytes,
            when=when,
        )
