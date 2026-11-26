"""Base de sesión mDoc ISO/IEC 18013-5 para pruebas con credenciales sintéticas.

No establece BLE ni verifica firmas. No transmite datos ni expone claves.
La validación de certificados, MSO, DeviceAuth y consentimiento sigue pendiente.
Dependencias `cbor2` y `cryptography` se cargan únicamente al ejecutarse.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
from dataclasses import dataclass, field
from typing import Any

from .inspect import MAX_SCAN_BYTES

_BODY = re.compile(rb"[A-Za-z0-9_-]+={0,2}\Z")
_MAX_ELEMENTS = 16


class MdocProtocolError(ValueError):
    """Error categórico sin incluir contenido del QR ni claves."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(repr=False)
class ReaderSessionMaterial:
    """Material efímero y confidencial; NUNCA imprimir o persistir."""

    engagement_profile: str
    session_transcript: bytes = field(repr=False)
    reader_cose_key: bytes = field(repr=False)
    reader_key: Any = field(repr=False)
    sk_reader: bytes = field(repr=False)
    sk_device: bytes = field(repr=False)

    def __repr__(self) -> str:
        return "<ReaderSessionMaterial (secret material redacted)>"


def _cbor_full(raw: bytes) -> Any:
    import cbor2

    buffer = io.BytesIO(raw)
    decoded = cbor2.CBORDecoder(buffer).decode()
    if buffer.read(1):
        raise MdocProtocolError("trailing_cbor_data")
    return decoded


def _engagement(raw: bytes) -> tuple[bytes, Any, str]:
    if not isinstance(raw, bytes) or not 6 <= len(raw) <= MAX_SCAN_BYTES:
        raise MdocProtocolError("invalid_qr")
    framed = raw.strip(b"\r\n\x00 \t")
    if framed[:5].lower() != b"mdoc:":
        raise MdocProtocolError("invalid_qr")
    encoded = framed[5:]
    if not encoded or not _BODY.fullmatch(encoded):
        raise MdocProtocolError("invalid_qr")
    try:
        decoded = base64.b64decode(
            encoded + b"=" * (-len(encoded) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise MdocProtocolError("invalid_base64url") from exc
    if not decoded or len(decoded) > MAX_SCAN_BYTES:
        raise MdocProtocolError("invalid_qr")
    try:
        root = _cbor_full(decoded)
    except (MdocProtocolError, RecursionError) as exc:
        raise MdocProtocolError("invalid_cbor") from exc
    if isinstance(root, list) and len(root) in (3, 4):
        version, security, methods = root[:3]
        profile = "iso_18013_array_candidate"
    elif isinstance(root, dict):
        version, security, methods = root.get(0), root.get(1), root.get(2)
        profile = "map_extension_candidate"
    else:
        raise MdocProtocolError("unsupported_engagement_structure")
    if version != "1.0" or not isinstance(methods, list) or not methods:
        raise MdocProtocolError("unsupported_engagement_version_or_methods")
    if not isinstance(security, list) or len(security) != 2 or security[0] != 1:
        raise MdocProtocolError("unsupported_cipher_suite")
    return decoded, security[1], profile


def _device_public_key(tagged_key: Any):
    import cbor2
    from cryptography.hazmat.primitives.asymmetric import ec

    if not isinstance(tagged_key, cbor2.CBORTag) or tagged_key.tag != 24:
        raise MdocProtocolError("invalid_device_key_tag")
    if not isinstance(tagged_key.value, bytes) or not 10 <= len(tagged_key.value) <= 512:
        raise MdocProtocolError("invalid_device_key_encoding")
    cose = _cbor_full(tagged_key.value)
    if not isinstance(cose, dict) or cose.get(1) != 2 or cose.get(-1) != 1:
        raise MdocProtocolError("unsupported_device_key")
    x, y = cose.get(-2), cose.get(-3)
    if not isinstance(x, bytes) or not isinstance(y, bytes) or len(x) != 32 or len(y) != 32:
        raise MdocProtocolError("invalid_p256_coordinates")
    try:
        return ec.EllipticCurvePublicNumbers(
            int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()
        ).public_key()
    except ValueError as exc:
        raise MdocProtocolError("invalid_p256_point") from exc


def prepare_reader_session(raw_qr: bytes) -> ReaderSessionMaterial:
    """Deriva material de sesión en memoria, SIN enviar ni autenticar una IDC."""
    import cbor2
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    engagement_bytes, device_tag, profile = _engagement(raw_qr)
    device_pub = _device_public_key(device_tag)

    # Clave efímera distinta para cada intento. No escribirla en disco.
    reader_priv = ec.generate_private_key(ec.SECP256R1())
    point = reader_priv.public_key().public_numbers()
    cose = {
        1: 2, -1: 1,
        -2: point.x.to_bytes(32, "big"),
        -3: point.y.to_bytes(32, "big"),
    }
    reader_key_bytes = cbor2.dumps(cose)
    transcript = cbor2.dumps([
        cbor2.CBORTag(24, engagement_bytes),
        cbor2.CBORTag(24, reader_key_bytes),
        None,  # QRHandover en ISO/IEC 18013-5
    ])
    transcript_bytes = cbor2.dumps(cbor2.CBORTag(24, transcript))
    salt = hashlib.sha256(transcript_bytes).digest()
    shared_secret = reader_priv.exchange(ec.ECDH(), device_pub)
    sk_reader = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"SKReader").derive(
        shared_secret
    )
    sk_device = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=b"SKDevice").derive(
        shared_secret
    )
    return ReaderSessionMaterial(
        engagement_profile=profile,
        session_transcript=transcript_bytes,
        reader_cose_key=reader_key_bytes,
        reader_key=reader_priv,
        sk_reader=sk_reader,
        sk_device=sk_device,
    )


def build_device_request(
    *,
    doc_type: str,
    requested_namespaces: dict[str, tuple[str, ...]],
) -> bytes:
    """Genera DeviceRequest sin readerAuth para pruebas sintéticas.

    Recibe esquema explícito; nunca presupone nombre de documento del TSE.
    El booleano False significa intención de retención desactivada.
    """
    import cbor2

    if not isinstance(doc_type, str) or not 1 <= len(doc_type) <= 128 or "\x00" in doc_type:
        raise MdocProtocolError("invalid_doc_type")
    if not isinstance(requested_namespaces, dict) or not 1 <= len(requested_namespaces) <= 8:
        raise MdocProtocolError("invalid_requested_namespaces")
    total = 0
    namespaces = {}
    for name, attributes in requested_namespaces.items():
        if not isinstance(name, str) or not 1 <= len(name) <= 128 or "\x00" in name:
            raise MdocProtocolError("invalid_namespace")
        if not isinstance(attributes, tuple) or not attributes or len(attributes) > _MAX_ELEMENTS:
            raise MdocProtocolError("invalid_attribute_selection")
        unique: dict[str, bool] = {}
        for attr in attributes:
            if not isinstance(attr, str) or not 1 <= len(attr) <= 128 or "\x00" in attr:
                raise MdocProtocolError("invalid_attribute")
            if attr in unique:
                raise MdocProtocolError("duplicate_attribute")
            unique[attr] = False
        total += len(unique)
        if total > _MAX_ELEMENTS:
            raise MdocProtocolError("too_many_attributes")
        namespaces[name] = unique
    items = cbor2.CBORTag(24, cbor2.dumps({"docType": doc_type, "nameSpaces": namespaces}))
    return cbor2.dumps({"version": "1.0", "docRequests": [{"itemsRequest": items}]})


def preflight_mdoc_crypto(raw_qr: bytes, *, consent: bool) -> dict[str, object]:
    """Solo metadatos; prueba de ECDH local, no verificación de documento."""
    report: dict[str, object] = {
        "schema_version": 1,
        "purpose": "offline_mdoc_crypto_preflight_only",
        "device_engagement_shape": "unknown",
        "supported_cipher_suite": False,
        "session_keys_derived_locally": False,
        "session_transcript_prepared": False,
        "ble_link_established": False,
        "mdoc_session_established": False,
        "issuer_signature_verified": False,
        "device_auth_verified": False,
        "iaca_trust_anchor_validated": False,
        "verified_identity": False,
        "idc_verification_available": False,
        "status": "consent_required",
    }
    if not consent:
        return report
    try:
        session = prepare_reader_session(raw_qr)
    except MdocProtocolError as exc:
        report["status"] = exc.code
    except (ImportError, ModuleNotFoundError):
        report["status"] = "optional_crypto_dependency_missing"
    except (Exception, RecursionError):
        # No devolver excepciones/bytes, que pueden contener datos sensibles.
        report["status"] = "invalid_or_unsupported_engagement"
    else:
        report["device_engagement_shape"] = session.engagement_profile
        report["supported_cipher_suite"] = True
        report["session_keys_derived_locally"] = True
        report["session_transcript_prepared"] = True
        report["status"] = "local_crypto_preflight_passed_not_verified"
    return report
