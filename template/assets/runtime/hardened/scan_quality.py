from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .models import EmptyPolicy, FieldAction


_UNKNOWN_VALUES = {
    "",
    "DESCONOCIDO",
    "DESCONOCIDA",
    "UNKNOWN",
    "N/A",
    "NA",
    "NONE",
    "NULL",
}
_NAME_RE = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ .'-]{2,90}$")


@dataclass(frozen=True, slots=True)
class QualityDecision:
    accepted: bool
    reason: str = "ok"


def _text(value: Any) -> str:
    return str(value or "").replace("\x00", " ").strip()


def _known(value: Any) -> bool:
    return _text(value).upper() not in _UNKNOWN_VALUES


def _cedula(value: Any) -> str:
    text = _text(value).replace("-", "").replace(" ", "")
    return text if text.isdigit() and 9 <= len(text) <= 12 else ""


def _date(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d/%m/%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _name(value: Any, *, optional: bool = False) -> bool:
    text = _text(value)
    if optional and not text:
        return True
    return _known(text) and bool(_NAME_RE.fullmatch(text))


def validate_parser_data(data: Mapping[str, Any], parser_id: str) -> QualityDecision:
    """Valida semánticamente el resultado antes de considerarlo una persona utilizable."""
    if not isinstance(data, Mapping):
        return QualityDecision(False, "data_not_mapping")

    parser = _text(parser_id).upper()
    if parser == "TSE_MDOC_ISO18013":
        url = _text(data.get("DocumentoURL"))
        if url.startswith("https://servicioidc.tse.go.cr/"):
            return QualityDecision(True)
        return QualityDecision(False, "mdoc_url_invalid")

    if not _cedula(data.get("Cedula")):
        return QualityDecision(False, "cedula_invalid")

    full_person_formats = {
        "MENOR_CSV",
        "ADULTO_XOR_CLASICO",
        "CEDULA_CSV_EXTENDIDA_V2",
    }
    has_person_names = any(
        _known(data.get(label))
        for label in ("Nombre", "Apellidos", "Primer Apellido", "Segundo Apellido")
    )
    if parser in full_person_formats or has_person_names:
        if not _name(data.get("Nombre")):
            return QualityDecision(False, "nombre_invalid")
        apellidos = _text(data.get("Apellidos"))
        primer_apellido = _text(data.get("Primer Apellido"))
        if not (_name(apellidos) or _name(primer_apellido)):
            return QualityDecision(False, "apellidos_invalid")
        if not _name(data.get("Segundo Apellido"), optional=True):
            return QualityDecision(False, "segundo_apellido_invalid")

    now = datetime.now(timezone.utc)
    for label in (
        "Fecha de Nacimiento",
        "Fecha de Expiracion",
        "Fecha de Expiración",
        "Fecha de Emision",
    ):
        raw = _text(data.get(label))
        if not raw:
            continue
        parsed = _date(raw)
        if parsed is None:
            return QualityDecision(False, f"date_invalid:{label}")
        if label == "Fecha de Nacimiento" and parsed > now:
            return QualityDecision(False, "birth_date_in_future")
        if label == "Fecha de Emision" and parsed.timestamp() > now.timestamp() + 86400:
            return QualityDecision(False, "issue_date_in_future")
        if parsed.year < 1900 or parsed.year > 2100:
            return QualityDecision(False, f"date_out_of_range:{label}")

    return QualityDecision(True)


def _resolved_value(data: Mapping[str, Any], action: FieldAction) -> str:
    value = _text(data.get(action.label))
    if value:
        return value
    if action.empty_policy == EmptyPolicy.DEFAULT:
        return _text(action.default_value)
    return ""


def validate_for_configuration(
    data: Mapping[str, Any],
    fields: Sequence[FieldAction],
) -> QualityDecision:
    """Impide tocar un formulario cuando faltan datos críticos solicitados."""
    for action in fields:
        value = _resolved_value(data, action)
        label = action.label

        if label == "Cedula":
            if not _cedula(value):
                return QualityDecision(False, "configured_cedula_missing")
            continue

        if label in {"Nombre", "Apellidos", "Primer Apellido", "Padre", "Madre"}:
            if not _name(value):
                return QualityDecision(False, f"configured_name_missing:{label}")
            continue

        if label == "Segundo Apellido":
            if value and not _name(value, optional=True):
                return QualityDecision(False, "configured_second_surname_invalid")
            continue

        if label.startswith("Fecha de "):
            if _date(value) is None:
                return QualityDecision(False, f"configured_date_missing:{label}")
            continue

        if action.empty_policy == EmptyPolicy.CANCEL and not value:
            return QualityDecision(False, f"configured_required_missing:{label}")

    return QualityDecision(True)


__all__ = [
    "QualityDecision",
    "validate_for_configuration",
    "validate_parser_data",
]
