"""Clasificación prudente sin revelar el contenido de un código QR."""
from __future__ import annotations

import base64
import binascii
import re

MAX_SCAN_BYTES = 32768
_MDOC_BODY = re.compile(rb"[A-Za-z0-9_-]+={0,2}\Z")
_CBOR_MAJOR = {
    0: "unsigned_integer",
    1: "negative_integer",
    2: "byte_string",
    3: "text_string",
    4: "array",
    5: "map",
    6: "tag",
    7: "simple_or_float",
}


def inspect_qr(raw: bytes) -> dict[str, object]:
    """Devuelve SOLO metadatos no identificadores. Nunca verifica un documento."""
    if not isinstance(raw, bytes):
        raise TypeError("La lectura debe ser bytes")
    if len(raw) > MAX_SCAN_BYTES:
        raise ValueError("Lectura mayor al límite permitido")
    framed = raw.strip(b"\r\n\x00 \t")
    report: dict[str, object] = {
        "schema_version": 1,
        "purpose": "format_diagnostic_only",
        "verified_identity": False,
        "raw_bytes": len(raw),
        "framed_bytes": len(framed),
        "classification": "other_or_unknown",
    }
    if not framed:
        report["classification"] = "empty"
        return report
    try:
        text = framed.decode("utf-8", errors="strict")
        report["utf8"] = True
    except UnicodeDecodeError:
        text = ""
        report["utf8"] = False

    if text[:5].casefold() == "mdoc:":
        report["classification"] = "mdoc_candidate"
        encoded = framed[5:]
        report["base64url_chars"] = len(encoded)
        if not _MDOC_BODY.fullmatch(encoded):
            report["base64url_valid"] = False
            return report
        try:
            decoded = base64.b64decode(
                encoded + b"=" * (-len(encoded) % 4),
                altchars=b"-_",
                validate=True,
            )
        except (binascii.Error, ValueError):
            report["base64url_valid"] = False
            return report
        report["base64url_valid"] = True
        report["decoded_bytes"] = len(decoded)
        if decoded:
            report["cbor_initial_major_type"] = _CBOR_MAJOR.get(decoded[0] >> 5, "unknown")
            report["cbor_indefinite_length"] = (decoded[0] & 31) == 31
        # No examina claves de sesión, certificados ni atributos personales.
        return report

    if text.casefold().startswith(("https://", "http://")):
        report["classification"] = "url_qr"
        report["url_has_query"] = "?" in text
    elif text.startswith(("CI", "ci")):
        report["classification"] = "short_code_candidate"
    elif not report["utf8"]:
        report["classification"] = "binary_or_non_utf8"
    else:
        report["classification"] = "text_or_other_qr"
    return report
