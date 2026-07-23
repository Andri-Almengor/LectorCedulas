from __future__ import annotations

from assets.runtime.hardened.models import FieldAction, FinalAction
from assets.runtime.hardened.scan_quality import (
    validate_for_configuration,
    validate_parser_data,
)


def complete_person():
    return {
        "TipoCedulaDetectado": "ADULTO_XOR_CLASICO",
        "Cedula": "119320121",
        "Apellidos": "ALMENGOR QUIROS",
        "Primer Apellido": "ALMENGOR",
        "Segundo Apellido": "QUIROS",
        "Nombre": "ANDRICK IVAN",
        "Fecha de Nacimiento": "24/03/2005",
        "Fecha de Expiracion": "06/02/2034",
        "Fecha de Expiración": "06/02/2034",
        "Fecha de Emision": "06/02/2024",
    }


def test_complete_person_is_accepted():
    decision = validate_parser_data(complete_person(), "ADULTO_XOR_CLASICO")
    assert decision.accepted


def test_truncated_identity_is_rejected_before_queue():
    data = complete_person()
    data["Cedula"] = "119"
    decision = validate_parser_data(data, "ADULTO_XOR_CLASICO")
    assert not decision.accepted
    assert decision.reason == "cedula_invalid"


def test_five_digit_tse_identity_is_rejected():
    data = {
        "TipoCedulaDetectado": "TSE_QR_URL",
        "Cedula": "12345",
        "Nombre": "DESCONOCIDO",
        "Apellidos": "DESCONOCIDO",
    }
    decision = validate_parser_data(data, "TSE_QR_URL")
    assert not decision.accepted
    assert decision.reason == "cedula_invalid"


def test_impossible_date_is_rejected_semantically():
    data = complete_person()
    data["Fecha de Nacimiento"] = "31/02/2005"
    decision = validate_parser_data(data, "ADULTO_XOR_CLASICO")
    assert not decision.accepted
    assert decision.reason == "date_invalid:Fecha de Nacimiento"


def test_fast_configuration_accepts_valid_identity_only():
    data = {
        "Cedula": "119320121",
        "Nombre": "DESCONOCIDO",
        "Apellidos": "DESCONOCIDO",
    }
    fields = (
        FieldAction("Cedula", action_after=FinalAction.NONE),
    )
    decision = validate_for_configuration(data, fields)
    assert decision.accepted


def test_full_configuration_rejects_placeholder_person_data():
    data = {
        "Cedula": "119320121",
        "Nombre": "DESCONOCIDO",
        "Apellidos": "DESCONOCIDO",
        "Fecha de Nacimiento": "",
    }
    fields = (
        FieldAction("Apellidos"),
        FieldAction("Nombre"),
        FieldAction("Cedula"),
        FieldAction("Fecha de Nacimiento", action_after=FinalAction.NONE),
    )
    decision = validate_for_configuration(data, fields)
    assert not decision.accepted
    assert decision.reason == "configured_name_missing:Apellidos"


def test_full_configuration_accepts_complete_values():
    data = complete_person()
    fields = (
        FieldAction("Apellidos"),
        FieldAction("Nombre"),
        FieldAction("Cedula"),
        FieldAction("Fecha de Nacimiento"),
        FieldAction("Fecha de Expiracion", action_after=FinalAction.NONE),
    )
    decision = validate_for_configuration(data, fields)
    assert decision.accepted


def test_second_surname_may_be_empty():
    data = complete_person()
    data["Segundo Apellido"] = ""
    fields = (
        FieldAction("Segundo Apellido", action_after=FinalAction.NONE),
    )
    decision = validate_for_configuration(data, fields)
    assert decision.accepted
