from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st

from assets.runtime.hardened.config_service import ConfigurationError, validate_configuration
from assets.runtime.hardened.url_security import UrlValidationError, validate_https_url


@given(st.binary(max_size=4096))
@settings(max_examples=150, deadline=None)
def test_arbitrary_raw_never_crashes_url_validator(raw):
    value = raw.decode("utf-8", errors="replace")
    try:
        result = validate_https_url(value, allowed_hosts={"www.consulta.tse.go.cr"})
        assert result.hostname == "www.consulta.tse.go.cr"
    except UrlValidationError:
        pass


@given(label=st.text(min_size=0, max_size=100), tabs=st.one_of(st.integers(min_value=-1000, max_value=1000), st.floats(allow_nan=True, allow_infinity=True)))
@settings(max_examples=150, deadline=None)
def test_arbitrary_config_fields_fail_closed(label, tabs):
    payload = {"nombre": "Fuzz", "campos": [{"dato": label, "tabuladores": tabs}]}
    try:
        snapshot = validate_configuration(payload, source_path="fuzz.json", generation=0)
        assert snapshot.fields[0].label in {"Cedula", "Apellidos", "Primer Apellido", "Segundo Apellido", "Nombre", "Sexo", "Fecha de Nacimiento", "Fecha de Expiracion", "Fecha de Expiración", "Fecha de Emision", "Lugar de Nacimiento", "Lugar de Residencia", "Padre", "Madre"}
        assert 0 <= snapshot.fields[0].tabs_before <= 50
    except (ConfigurationError, ValueError, TypeError, OverflowError):
        pass
