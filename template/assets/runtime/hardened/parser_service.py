from __future__ import annotations

import base64
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

from .format_engine import DeclarativeFormatEngine, FormatConfigurationError
from .privacy import technical_event
from .url_security import UrlValidationError, validate_https_url


@dataclass(slots=True)
class ParserResult:
    data: dict[str, Any]
    recognized: bool
    parser_id: str


class ParserService:
    """Aísla parsers y evita I/O de red dentro del hilo serial."""

    TSE_URL_RE = re.compile(r"https://[^\s\x00-\x20]+", re.IGNORECASE)

    def __init__(
        self,
        core_loader: Callable[[], Any],
        logger: Callable[[str], None] | None = None,
        *,
        formats_path=None,
    ):
        self.core_loader = core_loader
        self.logger = logger or (lambda message: None)
        self.format_engine = DeclarativeFormatEngine(formats_path) if formats_path else None

    @staticmethod
    def _decode(raw: bytes) -> str:
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    def _partial_tse_url(self, raw: bytes) -> ParserResult | None:
        text = self._decode(raw).strip()
        for candidate in self.TSE_URL_RE.findall(text):
            candidate = candidate.rstrip(".,;)]}\"'")
            try:
                validated = validate_https_url(
                    candidate,
                    allowed_hosts={"www.consulta.tse.go.cr"},
                )
            except UrlValidationError:
                continue
            if validated.path.casefold() != "/consultacedula/cedula":
                continue
            cedula = (validated.query.get("cedula") or [""])[0].strip()
            if not cedula.isdigit() or not 5 <= len(cedula) <= 12:
                continue
            data = {
                "TipoCedulaDetectado": "TSE_QR_URL",
                "Cedula": cedula,
                "Apellidos": "DESCONOCIDO",
                "Primer Apellido": "DESCONOCIDO",
                "Segundo Apellido": "",
                "Nombre": "DESCONOCIDO",
                "Sexo": "DESCONOCIDO",
                "Fecha de Nacimiento": "",
                "Fecha de Expiracion": "",
                "Fecha de Expiración": "",
                "Fecha de Emision": "",
                "TSE_URL": validated.url,
                "TSE_Consulta": "PENDIENTE",
            }
            return ParserResult(data, True, "TSE_QR_URL_SAFE")
        return None

    def _partial_mdoc(self, raw: bytes) -> ParserResult | None:
        text = self._decode(raw).strip()
        if not text.casefold().startswith("mdoc:"):
            return None
        payload = text.split(":", 1)[1].strip().split()[0]
        if not payload or len(payload) > 16384:
            return None
        try:
            decoded = base64.urlsafe_b64decode(payload + "=" * ((4 - len(payload) % 4) % 4))
        except Exception:
            return None
        candidates = re.findall(rb"https://[^\x00-\x20]+", decoded)
        for raw_url in candidates:
            try:
                url = raw_url.decode("utf-8", errors="strict").rstrip(".,;)]}\"'")
                validated = validate_https_url(
                    url,
                    allowed_hosts={"servicioidc.tse.go.cr"},
                )
            except (UnicodeDecodeError, UrlValidationError):
                continue
            data = {
                "TipoCedulaDetectado": "TSE_MDOC_ISO18013",
                "Cedula": "DESCONOCIDO",
                "Apellidos": "DESCONOCIDO",
                "Primer Apellido": "DESCONOCIDO",
                "Segundo Apellido": "",
                "Nombre": "DESCONOCIDO",
                "Sexo": "DESCONOCIDO",
                "Fecha de Nacimiento": "",
                "Fecha de Expiracion": "",
                "Fecha de Expiración": "",
                "Fecha de Emision": "",
                "DocumentoURL": validated.url,
                "MDocTipo": "ISO18013",
            }
            return ParserResult(data, True, "TSE_MDOC_SAFE")
        return None

    def parse(self, raw: bytes) -> ParserResult:
        if self.format_engine is not None:
            try:
                match = self.format_engine.parse(raw)
            except FormatConfigurationError as exc:
                self.logger(technical_event("format_configuration_error", error_type=type(exc).__name__))
                raise
            if match is not None:
                return ParserResult(match.data, not match.blocked, match.format_id)
        for parser in (self._partial_tse_url, self._partial_mdoc):
            result = parser(raw)
            if result is not None:
                return result
        core = self.core_loader()
        data = core.parse_cedula_unificada(raw)
        valid = bool(core._is_probably_valid_person(data))
        parser_id = str(data.get("TipoCedulaDetectado") or "UNKNOWN") if isinstance(data, dict) else "UNKNOWN"
        return ParserResult(dict(data or {}), valid, parser_id)


class TseEnrichmentService:
    """Consulta opcional fuera del listener, con límites estrictos y caché breve."""

    def __init__(
        self,
        core_loader: Callable[[], Any],
        logger: Callable[[str], None] | None = None,
        *,
        timeout_seconds: float = 3.0,
        max_bytes: int = 512_000,
        ttl_seconds: float = 60.0,
        max_entries: int = 16,
    ):
        self.core_loader = core_loader
        self.logger = logger or (lambda message: None)
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def _get_cached(self, url: str) -> dict[str, Any] | None:
        now = time.monotonic()
        with self._lock:
            item = self._cache.get(url)
            if not item:
                return None
            created, data = item
            if now - created > self.ttl_seconds:
                self._cache.pop(url, None)
                return None
            self._cache.move_to_end(url)
            return dict(data)

    def _store(self, url: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._cache[url] = (time.monotonic(), dict(data))
            self._cache.move_to_end(url)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)

    def enrich(self, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("TipoCedulaDetectado") != "TSE_QR_URL":
            return data
        url = str(data.get("TSE_URL") or "")
        cedula = str(data.get("Cedula") or "")
        try:
            validated = validate_https_url(url, allowed_hosts={"www.consulta.tse.go.cr"})
        except UrlValidationError:
            return data
        cached = self._get_cached(validated.url)
        if cached is not None:
            return cached
        try:
            import requests
            response = requests.get(
                validated.url,
                timeout=(self.timeout_seconds, self.timeout_seconds),
                allow_redirects=False,
                stream=True,
                headers={"Accept": "text/html", "User-Agent": "DMS-LectorCedulas/4"},
            )
            if response.status_code != 200:
                return data
            content_type = (response.headers.get("Content-Type") or "").casefold()
            if "text/html" not in content_type:
                return data
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=16384):
                total += len(chunk)
                if total > self.max_bytes:
                    self.logger(technical_event("tse_response_rejected", reason="size_limit"))
                    return data
                chunks.append(chunk)
            response.encoding = response.encoding or "utf-8"
            html = b"".join(chunks).decode(response.encoding, errors="replace")
            parsed = self.core_loader()._parse_tse_html(html, cedula)
            parsed["TSE_URL"] = validated.url
            parsed["TSE_Consulta"] = "OK"
            self._store(validated.url, parsed)
            return parsed
        except Exception as exc:
            self.logger(technical_event("tse_enrichment_failed", error_type=type(exc).__name__))
            return data
