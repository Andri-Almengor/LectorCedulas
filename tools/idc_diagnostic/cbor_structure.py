"""Inspección estructural CBOR sin exponer cadenas, claves ni bytes del QR.

Este analizador limitado NO verifica documentos, certificados, sesiones ni firmas.
"""
from __future__ import annotations

from dataclasses import dataclass

_MAX_NODES = 1024
_MAX_DEPTH = 12
_TRANSPORT_NAMES = {1: "NFC", 2: "BLE", 3: "Wi-Fi Aware"}


class _CborError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _Node:
    kind: str
    number: int | None = None
    version: str | None = None
    items: tuple["_Node", ...] = ()
    pairs: tuple[tuple["_Node", "_Node"], ...] = ()


class _Reader:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.offset = 0
        self.nodes = 0

    def _take(self, length: int) -> bytes:
        if length < 0 or length > len(self.raw) - self.offset:
            raise _CborError("truncated")
        start = self.offset
        self.offset += length
        return self.raw[start:self.offset]

    def _argument(self, additional: int) -> int:
        if additional < 24:
            return additional
        sizes = {24: 1, 25: 2, 26: 4, 27: 8}
        size = sizes.get(additional)
        if size is None:
            raise _CborError("unsupported_length")
        return int.from_bytes(self._take(size), "big")

    def item(self, depth: int = 0) -> _Node:
        self.nodes += 1
        if self.nodes > _MAX_NODES or depth > _MAX_DEPTH:
            raise _CborError("structure_limit")
        lead = self._take(1)[0]
        major, additional = lead >> 5, lead & 31
        count = self._argument(additional)
        if major == 0:
            return _Node("uint", number=count)
        if major == 1:
            return _Node("nint", number=-1 - count)
        if major == 2:
            self._take(count)
            return _Node("bytes")
        if major == 3:
            # No almacenar cadenas; reconocer únicamente versiones estandarizadas.
            value = self._take(count)
            try:
                value.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise _CborError("invalid_text") from exc
            version = value.decode("ascii") if value in (b"1.0", b"1.1") else None
            return _Node("text", version=version)
        if major == 4:
            if count > _MAX_NODES:
                raise _CborError("too_many_items")
            items = tuple(self.item(depth + 1) for _ in range(count))
            return _Node("array", items=items)
        if major == 5:
            if count > _MAX_NODES // 2:
                raise _CborError("too_many_items")
            pairs = tuple((self.item(depth + 1), self.item(depth + 1)) for _ in range(count))
            return _Node("map", pairs=pairs)
        if major == 6:
            # Etiqueta analizada solo a nivel estructural; su contenido no se divulga.
            return _Node("tag", items=(self.item(depth + 1),))
        if major == 7:
            return _Node("simple_or_float")
        raise _CborError("unknown_major")


def _methods(node: _Node | None) -> list[str] | None:
    if node is None or node.kind != "array":
        return None
    detected: set[str] = set()
    for entry in node.items:
        if entry.kind != "array" or len(entry.items) != 3:
            return None
        kind, version, _options = entry.items
        if kind.kind != "uint" or version.kind != "uint":
            return None
        name = _TRANSPORT_NAMES.get(kind.number)
        if name:
            detected.add(name)
    return sorted(detected)


def inspect_cbor_structure(raw: bytes) -> dict[str, object]:
    """Metadatos estructurales; nunca retorna valores CBOR originales."""
    result: dict[str, object] = {
        "cbor_structure_decoded": False,
        "cbor_profile_hint": "unidentified",
        "transport_candidates": [],
        "verified_identity": False,
    }
    try:
        reader = _Reader(raw)
        root = reader.item()
        if reader.offset != len(raw):
            raise _CborError("trailing_data")
    except (_CborError, RecursionError):
        return result

    result["cbor_structure_decoded"] = True
    result["cbor_root_items"] = len(root.pairs) if root.kind == "map" else (
        len(root.items) if root.kind == "array" else 0
    )
    retrieval: _Node | None = None
    if root.kind == "map":
        known: dict[int, _Node] = {}
        for key, value in root.pairs:
            if key.kind == "uint" and key.number is not None and 0 <= key.number <= 6:
                if key.number in known:
                    result["cbor_structure_decoded"] = False
                    return result
                known[key.number] = value
        result["known_engagement_fields_present"] = sorted(known.keys())
        if (
            0 in known
            and known[0].kind == "text"
            and known[0].version is not None
            and 1 in known
        ):
            result["cbor_profile_hint"] = "iso_23220_map_shape_candidate"
            retrieval = known.get(2)
    elif root.kind == "array" and len(root.items) >= 2:
        if root.items[0].kind == "text" and root.items[0].version is not None:
            result["cbor_profile_hint"] = "iso_18013_array_shape_candidate"
            if len(root.items) >= 3:
                retrieval = root.items[2]

    if result["cbor_profile_hint"] != "unidentified":
        methods = _methods(retrieval)
        if methods is not None:
            result["transport_candidates"] = methods
    return result
