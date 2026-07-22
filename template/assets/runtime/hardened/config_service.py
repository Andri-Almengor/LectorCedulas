from __future__ import annotations

import hashlib
import math
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .atomic_io import AtomicJsonError, read_json, write_json_atomic
from .models import EmptyPolicy, FieldAction, FinalAction, ValidationType
from .version import CONFIG_SCHEMA_VERSION

KNOWN_LABELS = {
    "Cedula",
    "Apellidos",
    "Primer Apellido",
    "Segundo Apellido",
    "Nombre",
    "Sexo",
    "Fecha de Nacimiento",
    "Fecha de Expiracion",
    "Fecha de Expiración",
    "Fecha de Emision",
    "Lugar de Nacimiento",
    "Lugar de Residencia",
    "Padre",
    "Madre",
}

_PROFILE_ALIASES = {
    "rapida": "rapida",
    "rápida": "rapida",
    "equilibrada": "equilibrada",
    "normal": "equilibrada",
    "segura": "maxima_compatibilidad",
    "máxima compatibilidad": "maxima_compatibilidad",
    "maxima_compatibilidad": "maxima_compatibilidad",
}


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ConfigurationSnapshot:
    schema_version: int
    configuration_id: str
    name: str
    profile: str
    validate_write: bool
    replace_content: bool
    final_action: FinalAction
    fields: tuple[FieldAction, ...]
    generation: int
    source_path: str


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return normalized[:64] or "configuracion"


def _bounded_int(value: Any, minimum: int, maximum: int, field_name: str) -> int:
    if isinstance(value, bool):
        raise ConfigurationError(f"{field_name} no puede ser booleano")
    try:
        converted = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field_name} debe ser un entero") from exc
    if converted < minimum or converted > maximum:
        raise ConfigurationError(f"{field_name} debe estar entre {minimum} y {maximum}")
    return converted


def _bounded_float(value: Any, minimum: float, maximum: float, field_name: str) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field_name} debe ser numérico") from exc
    if not math.isfinite(converted) or converted < minimum or converted > maximum:
        raise ConfigurationError(f"{field_name} debe estar entre {minimum} y {maximum}")
    return converted


def migrate_configuration(payload: dict[str, Any], *, fallback_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ConfigurationError("La configuración debe ser un objeto JSON")
    schema = payload.get("schema_version")
    if schema in (None, 0, 1):
        name = str(payload.get("nombre") or fallback_name).strip()
        migrated_fields: list[dict[str, Any]] = []
        for legacy in payload.get("campos") or []:
            if not isinstance(legacy, dict):
                raise ConfigurationError("Cada campo debe ser un objeto")
            migrated_fields.append(
                {
                    "dato": legacy.get("dato", ""),
                    "tabuladores": legacy.get("tabuladores", 0),
                    "politica_vacio": legacy.get("politica_vacio", "conservar"),
                    "valor_predeterminado": legacy.get("valor_predeterminado", ""),
                    "reemplazar": legacy.get("reemplazar", payload.get("reemplazar_contenido", False)),
                    "validacion": legacy.get("validacion", "none"),
                    "comparacion_normalizada": legacy.get("comparacion_normalizada", False),
                    "espera_adicional": legacy.get("espera_adicional", 0.0),
                    "accion_posterior": legacy.get("accion_posterior", "tab"),
                }
            )
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "id": str(payload.get("id") or _slug(name)),
            "nombre": name,
            "perfil_escritura": payload.get("perfil_escritura") or payload.get("velocidad_escritura") or "rapida",
            "validar_escritura": bool(payload.get("validar_escritura", True)),
            "reemplazar_contenido": bool(payload.get("reemplazar_contenido", False)),
            "accion_final": payload.get("accion_final", "tab"),
            "campos": migrated_fields,
        }
    if schema != CONFIG_SCHEMA_VERSION:
        raise ConfigurationError(f"schema_version no soportado: {schema}")
    return dict(payload)


def validate_configuration(payload: dict[str, Any], *, source_path: str, generation: int) -> ConfigurationSnapshot:
    migrated = migrate_configuration(payload, fallback_name=Path(source_path).stem)
    name = str(migrated.get("nombre") or "").strip()
    if not name or len(name) > 120:
        raise ConfigurationError("nombre inválido")
    configuration_id = _slug(str(migrated.get("id") or name))
    raw_profile = str(migrated.get("perfil_escritura") or "rapida").strip().casefold()
    profile = _PROFILE_ALIASES.get(raw_profile, raw_profile)
    if profile not in {"rapida", "equilibrada", "maxima_compatibilidad"}:
        raise ConfigurationError(f"perfil_escritura desconocido: {raw_profile}")
    try:
        final_action = FinalAction(str(migrated.get("accion_final", "none")))
    except ValueError as exc:
        raise ConfigurationError("accion_final inválida") from exc

    raw_fields = migrated.get("campos")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ConfigurationError("La configuración debe contener al menos un campo")
    if len(raw_fields) > 64:
        raise ConfigurationError("La configuración excede 64 campos")

    seen_labels: set[str] = set()
    fields: list[FieldAction] = []
    for index, raw in enumerate(raw_fields, start=1):
        if not isinstance(raw, dict):
            raise ConfigurationError(f"Campo {index}: debe ser un objeto")
        label = str(raw.get("dato") or "").strip()
        if not label or len(label) > 80:
            raise ConfigurationError(f"Campo {index}: etiqueta inválida")
        if label in seen_labels:
            raise ConfigurationError(f"Campo duplicado: {label}")
        seen_labels.add(label)
        if label not in KNOWN_LABELS:
            raise ConfigurationError(f"Etiqueta desconocida: {label}")

        tabs = _bounded_int(raw.get("tabuladores", 0), 0, 50, f"Campo {label}: tabuladores")
        empty_raw = str(raw.get("politica_vacio", "conservar")).casefold()
        empty_aliases = {
            "conservar": EmptyPolicy.PRESERVE,
            "preserve": EmptyPolicy.PRESERVE,
            "limpiar": EmptyPolicy.CLEAR,
            "clear": EmptyPolicy.CLEAR,
            "predeterminado": EmptyPolicy.DEFAULT,
            "default": EmptyPolicy.DEFAULT,
            "cancelar": EmptyPolicy.CANCEL,
            "cancel": EmptyPolicy.CANCEL,
        }
        if empty_raw not in empty_aliases:
            raise ConfigurationError(f"Campo {label}: politica_vacio inválida")

        validate_globally = bool(migrated.get("validar_escritura", True))
        inferred_validation = "none"
        if validate_globally:
            if label == "Cedula":
                inferred_validation = "cedula"
            elif label.startswith("Fecha de "):
                inferred_validation = "fecha"
            elif label == "Sexo":
                inferred_validation = "sexo"
            elif label in {"Nombre", "Apellidos", "Primer Apellido", "Segundo Apellido", "Padre", "Madre"}:
                inferred_validation = "nombre"
            else:
                inferred_validation = "texto"
        validation_raw = str(raw.get("validacion") or inferred_validation).casefold()
        validation_aliases = {
            "none": ValidationType.NONE,
            "ninguna": ValidationType.NONE,
            "texto": ValidationType.STRICT_TEXT,
            "strict_text": ValidationType.STRICT_TEXT,
            "cedula": ValidationType.CEDULA,
            "fecha": ValidationType.DATE,
            "date": ValidationType.DATE,
            "sexo": ValidationType.SEX,
            "sex": ValidationType.SEX,
            "nombre": ValidationType.NAME,
            "name": ValidationType.NAME,
        }
        if validation_raw not in validation_aliases:
            raise ConfigurationError(f"Campo {label}: validacion inválida")
        try:
            action_after = FinalAction(str(raw.get("accion_posterior", "tab")))
        except ValueError as exc:
            raise ConfigurationError(f"Campo {label}: accion_posterior inválida") from exc
        extra_wait = _bounded_float(raw.get("espera_adicional", 0.0), 0.0, 5.0, f"Campo {label}: espera_adicional")
        custom = raw.get("combinacion_personalizada") or []
        if not isinstance(custom, list) or len(custom) > 4 or not all(isinstance(item, str) and item for item in custom):
            raise ConfigurationError(f"Campo {label}: combinación personalizada inválida")

        fields.append(
            FieldAction(
                label=label,
                tabs_before=tabs,
                empty_policy=empty_aliases[empty_raw],
                default_value=str(raw.get("valor_predeterminado") or ""),
                replace_existing=bool(raw.get("reemplazar", migrated.get("reemplazar_contenido", False))),
                validation=validation_aliases[validation_raw],
                normalized_compare=bool(raw.get("comparacion_normalizada", False)),
                extra_wait=extra_wait,
                action_after=action_after,
                custom_action=tuple(custom),
            )
        )

    return ConfigurationSnapshot(
        schema_version=CONFIG_SCHEMA_VERSION,
        configuration_id=configuration_id,
        name=name,
        profile=profile,
        validate_write=bool(migrated.get("validar_escritura", True)),
        replace_content=bool(migrated.get("reemplazar_contenido", False)),
        final_action=final_action,
        fields=tuple(fields),
        generation=generation,
        source_path=source_path,
    )


class ConfigurationService:
    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.forms_dir = self.root / "formularios"
        self.system_dir = self.root / "sistema"
        self.active_path = self.system_dir / "config_actual.json"
        self.favorites_path = self.system_dir / "favoritos.json"
        self.last_com_path = self.system_dir / "ultimo_com.json"
        self._lock = threading.RLock()
        self._generation = 0

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def initialize(self) -> None:
        self.forms_dir.mkdir(parents=True, exist_ok=True)
        self.system_dir.mkdir(parents=True, exist_ok=True)
        default_path = self.forms_dir / "formulario_visitantes.json"
        if not default_path.exists():
            write_json_atomic(
                default_path,
                {
                    "schema_version": CONFIG_SCHEMA_VERSION,
                    "id": "formulario-visitantes",
                    "nombre": "Formulario Visitantes",
                    "perfil_escritura": "equilibrada",
                    "validar_escritura": True,
                    "reemplazar_contenido": False,
                    "accion_final": "none",
                    "campos": [
                        {"dato": "Primer Apellido", "tabuladores": 0, "politica_vacio": "conservar", "accion_posterior": "tab"},
                        {"dato": "Nombre", "tabuladores": 0, "politica_vacio": "conservar", "accion_posterior": "tab"},
                        {"dato": "Cedula", "tabuladores": 1, "politica_vacio": "conservar", "validacion": "cedula", "accion_posterior": "tab"},
                        {"dato": "Fecha de Nacimiento", "tabuladores": 2, "politica_vacio": "conservar", "validacion": "fecha", "accion_posterior": "none"},
                    ],
                },
                backup=False,
            )
        if not self.active_path.exists():
            write_json_atomic(self.active_path, {"activa": default_path.name}, backup=False)
        if not self.favorites_path.exists():
            write_json_atomic(self.favorites_path, {"favorito_1": "", "favorito_2": ""}, backup=False)

    def list_forms(self) -> list[str]:
        return sorted((path.name for path in self.forms_dir.glob("*.json") if path.is_file()), key=str.casefold)

    def _active_filename(self) -> str:
        data = read_json(self.active_path, required=True)
        name = os.path.basename(str(data.get("activa") or ""))
        if not name:
            raise ConfigurationError("No hay configuración activa")
        if name not in self.list_forms():
            raise ConfigurationError(f"La configuración activa no existe: {name}")
        return name

    def load_active(self) -> ConfigurationSnapshot:
        with self._lock:
            name = self._active_filename()
            path = self.forms_dir / name
            try:
                payload = read_json(path, required=True)
            except AtomicJsonError as exc:
                raise ConfigurationError(str(exc)) from exc
            snapshot = validate_configuration(payload, source_path=str(path), generation=self._generation)
            migrated = migrate_configuration(payload, fallback_name=path.stem)
            if payload != migrated:
                write_json_atomic(path, migrated)
            return snapshot

    def set_active(self, name: str) -> int:
        filename = os.path.basename(str(name or ""))
        path = self.forms_dir / filename
        if filename not in self.list_forms():
            raise ConfigurationError("La configuración seleccionada no existe")
        payload = read_json(path, required=True)
        validate_configuration(payload, source_path=str(path), generation=self._generation + 1)
        with self._lock:
            self._generation += 1
            write_json_atomic(self.active_path, {"activa": filename})
            return self._generation

    def favorites(self) -> tuple[str, str]:
        data = read_json(self.favorites_path, default={}) or {}
        available = set(self.list_forms())
        first = os.path.basename(str(data.get("favorito_1") or ""))
        second = os.path.basename(str(data.get("favorito_2") or ""))
        return (first if first in available else "", second if second in available else "")

    def toggle_favorite(self) -> tuple[str, int]:
        first, second = self.favorites()
        if not first or not second or first == second:
            raise ConfigurationError("Defina dos favoritas distintas")
        active = self._active_filename()
        target = second if active == first else first
        generation = self.set_active(target)
        return target, generation

    def save_last_port(self, metadata: dict[str, Any]) -> None:
        allowed = {key: metadata.get(key) for key in ("device", "vid", "pid", "serial_number", "manufacturer", "description")}
        write_json_atomic(self.last_com_path, allowed)

    def load_last_port(self) -> dict[str, Any]:
        data = read_json(self.last_com_path, default={}) or {}
        return data if isinstance(data, dict) else {}
