from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit


class UrlValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedUrl:
    url: str
    hostname: str
    path: str
    query: dict[str, list[str]]


ALLOWED_TSE_HOSTS = {
    "www.consulta.tse.go.cr",
    "servicioidc.tse.go.cr",
}


def validate_https_url(
    value: str,
    *,
    allowed_hosts: set[str] | frozenset[str] = frozenset(ALLOWED_TSE_HOSTS),
    allowed_ports: set[int | None] | frozenset[int | None] = frozenset({None, 443}),
    max_length: int = 4096,
) -> ValidatedUrl:
    text = str(value or "").strip()
    if not text or len(text) > max_length:
        raise UrlValidationError("url_vacia_o_demasiado_larga")
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError as exc:
        raise UrlValidationError("url_mal_formada") from exc
    if parsed.scheme != "https":
        raise UrlValidationError("esquema_no_permitido")
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    if hostname not in {host.casefold() for host in allowed_hosts}:
        raise UrlValidationError("hostname_no_permitido")
    if port not in allowed_ports:
        raise UrlValidationError("puerto_no_permitido")
    if parsed.username is not None or parsed.password is not None:
        raise UrlValidationError("credenciales_embebidas")
    if not parsed.path.startswith("/"):
        raise UrlValidationError("ruta_invalida")
    return ValidatedUrl(
        url=text,
        hostname=hostname,
        path=parsed.path,
        query=parse_qs(parsed.query, keep_blank_values=True, strict_parsing=False),
    )
