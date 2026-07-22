from __future__ import annotations

import base64

from assets.runtime.hardened.parser_service import ParserService


class FakeCore:
    @staticmethod
    def parse_cedula_unificada(raw):
        return {"TipoCedulaDetectado": "ADULTO_XOR", "Cedula": "123", "Nombre": "ANA"}

    @staticmethod
    def _is_probably_valid_person(data):
        return data.get("TipoCedulaDetectado") == "ADULTO_XOR"


def service():
    return ParserService(lambda: FakeCore())


def test_tse_url_is_parsed_offline_without_calling_legacy_network():
    raw = b"https://www.consulta.tse.go.cr/consultacedula/Cedula?cedula=123456789&sign=secret"
    result = service().parse(raw)
    assert result.recognized
    assert result.data["Cedula"] == "123456789"
    assert result.data["TSE_Consulta"] == "PENDIENTE"


def test_fake_tse_domain_is_not_accepted_as_tse():
    raw = b"https://www.consulta.tse.go.cr.evil.test/consultacedula/Cedula?cedula=123456789"
    assert service().parse(raw).parser_id == "ADULTO_XOR"


def test_mdoc_requires_exact_service_host():
    payload = base64.urlsafe_b64encode(b"x https://servicioidc.tse.go.cr/api/test y").rstrip(b"=")
    assert service().parse(b"mdoc:" + payload).parser_id == "TSE_MDOC_SAFE"
    evil = base64.urlsafe_b64encode(b"https://servicioidc.tse.go.cr.evil.test/x").rstrip(b"=")
    assert service().parse(b"mdoc:" + evil).parser_id == "ADULTO_XOR"
