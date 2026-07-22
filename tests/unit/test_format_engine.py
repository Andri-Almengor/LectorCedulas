from __future__ import annotations

import json

from assets.runtime.hardened.format_engine import DeclarativeFormatEngine


def write_formats(tmp_path, formats):
    path = tmp_path / "formatos.json"
    path.write_text(json.dumps({"version": 1, "formatos": formats}), encoding="utf-8")
    return path


def test_csv_declarative_format(tmp_path):
    path = write_formats(tmp_path, [{"id": "CSV", "enabled": True, "tipo": "csv", "inicio_regex": '"(\\d{9})",', "min_fields": 8, "fields": {"Cedula": 0, "Fecha de Nacimiento": 2, "Primer Apellido": 5, "Segundo Apellido": 6, "Nombre": 7}, "date_format": "ddmmyyyy", "required": ["Cedula", "Nombre", "Primer Apellido"], "validators": {"Cedula": {"regex": "^\\d{9}$"}}}])
    raw = b'"123456789",01012020,02022010,"P","M",MUNOZ,QUIROS,"ANA"'
    match = DeclarativeFormatEngine(path).parse(raw)
    assert match and match.data["Cedula"] == "123456789"
    assert match.data["Fecha de Nacimiento"] == "02/02/2010"
    assert match.data["Apellidos"] == "MUNOZ QUIROS"


def test_fixed_xor_declarative_format(tmp_path):
    key = [1, 2]
    decoded = b"123456789ANA       M"
    encoded = bytes(value ^ key[index % len(key)] for index, value in enumerate(decoded))
    path = write_formats(tmp_path, [{"id": "XOR", "enabled": True, "tipo": "xor_fixed_offsets", "min_len": len(decoded), "max_len": len(decoded), "xor_key": key, "fields": {"Cedula": {"start": 0, "length": 9}, "Nombre": {"start": 9, "length": 10}, "Primer Apellido": {"start": 9, "length": 3}, "Sexo": {"start": 19, "length": 1}}, "sexo_map": {"M": "MASCULINO"}, "required": ["Cedula", "Nombre", "Primer Apellido"]}])
    match = DeclarativeFormatEngine(path).parse(encoded)
    assert match and match.format_id == "XOR"
    assert match.data["Sexo"] == "MASCULINO"


def test_blocked_signature_never_returns_person(tmp_path):
    path = write_formats(tmp_path, [{"id": "BLOCK", "enabled": True, "tipo": "binary_unknown", "min_len": 4, "max_len": 20, "signature_hex_prefix": "deadbeef", "block_write": True}])
    match = DeclarativeFormatEngine(path).parse(bytes.fromhex("deadbeef00"))
    assert match and match.blocked and match.data == {}


def test_disabled_format_is_ignored(tmp_path):
    path = write_formats(tmp_path, [{"id": "SHORT", "enabled": False, "tipo": "short_code", "inicio_regex": "^CI(\\d{9})$", "min_len": 11, "max_len": 11, "fields": {"Cedula": {"regex_extract": "CI(\\d{9})"}}, "required": ["Cedula"]}])
    assert DeclarativeFormatEngine(path).parse(b"CI123456789") is None


def test_url_date_does_not_accept_non_date_token(tmp_path):
    path = write_formats(tmp_path, [{"id": "TSE_QR_URL", "enabled": True, "tipo": "url_querystring", "inicio_regex": "^https://www\\.consulta\\.tse\\.go\\.cr/consultacedula/Cedula\\?", "min_len": 20, "max_len": 250, "fields": {"Cedula": {"query_param": "cedula"}, "Fecha de Emision": {"query_param": "sol"}}, "required": ["Cedula"], "validators": {"Cedula": {"regex": "^\\d{9}$"}}}])
    raw = b"https://www.consulta.tse.go.cr/consultacedula/Cedula?cedula=123456789&sol=202611101736"
    match = DeclarativeFormatEngine(path).parse(raw)
    assert match and match.data["Fecha de Emision"] == ""
