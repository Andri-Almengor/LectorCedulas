from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .atomic_io import AtomicJsonError, read_json
from .url_security import UrlValidationError, validate_https_url


class FormatConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FormatMatch:
    format_id: str
    data: dict[str, Any]
    blocked: bool = False


def _safe_pattern(pattern: Any, *, max_length: int = 256) -> re.Pattern[str]:
    text = str(pattern or "")
    if not text or len(text) > max_length:
        raise FormatConfigurationError("Regex vacía o demasiado larga")
    lowered = text.casefold()
    if any(token in text for token in ("(?=", "(?!", "(?<=", "(?<!", "\\1", "\\2", "\\g")):
        raise FormatConfigurationError("Regex usa una construcción no permitida")
    if re.search(r"\([^)]*[+*][^)]*\)[+*{]", text):
        raise FormatConfigurationError("Regex contiene cuantificadores anidados")
    try:
        return re.compile(text)
    except re.error as exc:
        raise FormatConfigurationError(f"Regex inválida: {exc}") from exc


def _decode(raw: bytes, encodings: list[str] | None = None) -> str:
    for encoding in encodings or ["utf-8-sig", "cp1252", "latin-1"]:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _date(value: str, kind: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    fmt = "%d%m%Y" if kind == "ddmmyyyy" else "%Y%m%d" if kind == "yyyymmdd" else ""
    if not fmt:
        return text
    try:
        return datetime.strptime(text, fmt).strftime("%d/%m/%Y")
    except ValueError:
        return ""


def _base() -> dict[str, Any]:
    return {
        "Cedula": "",
        "Apellidos": "",
        "Primer Apellido": "",
        "Segundo Apellido": "",
        "Nombre": "",
        "Sexo": "DESCONOCIDO",
        "Fecha de Nacimiento": "",
        "Fecha de Expiracion": "",
        "Fecha de Expiración": "",
        "Fecha de Emision": "",
    }


class DeclarativeFormatEngine:
    """Motor declarativo limitado a operaciones allowlist y sin ejecución dinámica."""

    SUPPORTED_TYPES = {
        "csv",
        "fixed_offsets",
        "xor_fixed_offsets",
        "short_code",
        "url_querystring",
        "binary_signature",
        "binary_unknown",
        "blocked",
    }

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._mtime_ns = -1
        self._formats: tuple[dict[str, Any], ...] = ()

    def _load(self) -> tuple[dict[str, Any], ...]:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return ()
        if stat.st_mtime_ns == self._mtime_ns:
            return self._formats
        try:
            document = read_json(self.path, required=True)
        except AtomicJsonError as exc:
            raise FormatConfigurationError(str(exc)) from exc
        if not isinstance(document, dict) or not isinstance(document.get("formatos"), list):
            raise FormatConfigurationError("formatos_cedulas.json inválido")
        formats: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in document["formatos"]:
            if not isinstance(raw, dict):
                raise FormatConfigurationError("Cada formato debe ser un objeto")
            format_id = str(raw.get("id") or "").strip()
            kind = str(raw.get("tipo") or "").strip()
            if not format_id or format_id in seen:
                raise FormatConfigurationError("ID de formato vacío o duplicado")
            seen.add(format_id)
            if kind not in self.SUPPORTED_TYPES and kind not in {"mdoc_url"}:
                raise FormatConfigurationError(f"Tipo de formato no soportado: {kind}")
            if raw.get("inicio_regex"):
                _safe_pattern(raw["inicio_regex"])
            formats.append(dict(raw))
        formats.sort(key=lambda item: int(item.get("priority", 0)), reverse=True)
        self._formats = tuple(formats)
        self._mtime_ns = stat.st_mtime_ns
        return self._formats

    @staticmethod
    def _length_matches(config: dict[str, Any], raw: bytes) -> bool:
        minimum = int(config.get("min_len", 0) or 0)
        maximum = int(config.get("max_len", 4096) or 4096)
        return 0 <= minimum <= len(raw) <= min(maximum, 4096)

    @staticmethod
    def _apply_common(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
        result = _base()
        result.update(config.get("default_values") or {})
        result.update(data)
        first = str(result.get("Primer Apellido") or "").strip()
        second = str(result.get("Segundo Apellido") or "").strip()
        if not result.get("Apellidos") and (first or second):
            result["Apellidos"] = f"{first} {second}".strip()
        sex_map = config.get("sexo_map") or {}
        if result.get("Sexo") in sex_map:
            result["Sexo"] = sex_map[result["Sexo"]]
        for field in config.get("remove_leading_zero") or []:
            value = str(result.get(field) or "")
            result[field] = value.lstrip("0") or "0"
        required = config.get("required") or []
        if any(not str(result.get(field) or "").strip() for field in required):
            return None
        for field, rule in (config.get("validators") or {}).items():
            value = str(result.get(field) or "")
            if not isinstance(rule, dict):
                return None
            if rule.get("regex") and not _safe_pattern(rule["regex"]).fullmatch(value):
                return None
            if len(value) < int(rule.get("min_length", 0) or 0):
                return None
            if len(value) > int(rule.get("max_length", 256) or 256):
                return None
        result["TipoCedulaDetectado"] = str(config.get("id"))
        return result

    def _match_start(self, config: dict[str, Any], text: str) -> re.Match[str] | None:
        pattern = config.get("inicio_regex")
        if not pattern:
            return re.match(r"", text)
        return _safe_pattern(pattern).search(text)

    def _parse_csv(self, config: dict[str, Any], raw: bytes) -> dict[str, Any] | None:
        text = _decode(raw, config.get("encoding_order"))
        start = self._match_start(config, text)
        if not start:
            return None
        line = text[start.start():].splitlines()[0].replace("\x00", "")
        if config.get("trim_binary_after_ascii"):
            line = "".join(char for char in line if char in "\t\r\n" or 32 <= ord(char) <= 126 or char.isalpha())
        try:
            fields = next(csv.reader(io.StringIO(line), delimiter=str(config.get("delimiter", ",")), quotechar=str(config.get("quotechar", '"'))))
        except (csv.Error, StopIteration):
            return None
        if len(fields) < int(config.get("min_fields", 1)):
            return None
        data: dict[str, Any] = {}
        for label, index in (config.get("fields") or {}).items():
            if isinstance(index, int) and 0 <= index < len(fields):
                data[label] = fields[index].strip()
        result = self._apply_common(data, config)
        if result is None:
            return None
        date_format = str(config.get("date_format") or "")
        for label in ("Fecha de Emision", "Fecha de Nacimiento", "Fecha de Expiracion", "Fecha de Expiración"):
            if label in result:
                result[label] = _date(result[label], date_format)
        return result

    def _parse_fixed(self, config: dict[str, Any], raw: bytes, *, xor: bool) -> dict[str, Any] | None:
        if not self._length_matches(config, raw):
            return None
        decoded = bytearray(raw)
        if xor:
            key = config.get("xor_key")
            if not isinstance(key, list) or not key or len(key) > 256 or any(not isinstance(item, int) or not 0 <= item <= 255 for item in key):
                raise FormatConfigurationError("xor_key inválida")
            decoded = bytearray(value ^ key[index % len(key)] for index, value in enumerate(decoded))
        data: dict[str, Any] = {}
        for label, location in (config.get("fields") or {}).items():
            if not isinstance(location, dict):
                return None
            start = int(location.get("start", -1))
            length = int(location.get("length", 0))
            if start < 0 or length < 1 or start + length > len(decoded):
                return None
            value = _decode(bytes(decoded[start:start + length]), config.get("encoding_order"))
            data[label] = value.split("\x00", 1)[0].strip()
        result = self._apply_common(data, config)
        if result is None:
            return None
        date_format = str(config.get("date_format") or "")
        for label in ("Fecha de Emision", "Fecha de Nacimiento", "Fecha de Expiracion", "Fecha de Expiración"):
            if label in result:
                result[label] = _date(result[label], date_format)
        return result

    def _parse_short(self, config: dict[str, Any], raw: bytes) -> dict[str, Any] | None:
        if not self._length_matches(config, raw):
            return None
        text = _decode(raw).strip()
        if not self._match_start(config, text):
            return None
        data: dict[str, Any] = {}
        for label, rule in (config.get("fields") or {}).items():
            if isinstance(rule, dict) and rule.get("regex_extract"):
                match = _safe_pattern(rule["regex_extract"]).search(text)
                if match:
                    data[label] = match.group(1) if match.groups() else match.group(0)
        return self._apply_common(data, config)

    def _parse_url(self, config: dict[str, Any], raw: bytes) -> dict[str, Any] | None:
        text = _decode(raw).strip()
        if not self._length_matches(config, raw) or not self._match_start(config, text):
            return None
        try:
            validated = validate_https_url(text, allowed_hosts={"www.consulta.tse.go.cr"})
        except UrlValidationError:
            return None
        data: dict[str, Any] = {"TSE_URL": validated.url}
        for label, rule in (config.get("fields") or {}).items():
            if isinstance(rule, dict) and rule.get("query_param"):
                value = (validated.query.get(str(rule["query_param"])) or [""])[0]
                if label.startswith("Fecha de ") and not (len(value) == 8 and value.isdigit()):
                    value = ""
                data[label] = value
        return self._apply_common(data, config)

    def _matches_binary_signature(self, config: dict[str, Any], raw: bytes) -> bool:
        if not self._length_matches(config, raw):
            return False
        prefix = str(config.get("signature_hex_prefix") or "").casefold()
        if prefix and not raw.hex().startswith(prefix):
            return False
        for item in config.get("contains_bytes") or []:
            try:
                needle = bytes.fromhex(str(item))
            except ValueError:
                raise FormatConfigurationError("contains_bytes contiene hex inválido")
            if needle and needle not in raw:
                return False
        return bool(prefix or config.get("contains_bytes"))

    def parse(self, raw: bytes) -> FormatMatch | None:
        if not isinstance(raw, (bytes, bytearray)) or not raw or len(raw) > 4096:
            return None
        for config in self._load():
            if not bool(config.get("enabled", True)):
                continue
            kind = str(config.get("tipo"))
            format_id = str(config.get("id"))
            if kind == "mdoc_url":
                continue
            if kind in {"binary_signature", "binary_unknown", "blocked"}:
                if self._matches_binary_signature(config, bytes(raw)):
                    return FormatMatch(format_id, {}, blocked=bool(config.get("block_write", True)))
                continue
            if kind == "csv":
                data = self._parse_csv(config, bytes(raw))
            elif kind == "fixed_offsets":
                data = self._parse_fixed(config, bytes(raw), xor=False)
            elif kind == "xor_fixed_offsets":
                data = self._parse_fixed(config, bytes(raw), xor=True)
            elif kind == "short_code":
                data = self._parse_short(config, bytes(raw))
            elif kind == "url_querystring":
                data = self._parse_url(config, bytes(raw))
            else:
                data = None
            if data is not None:
                return FormatMatch(format_id, data)
        return None
