from __future__ import annotations

import pytest

from assets.runtime.hardened.atomic_io import AtomicJsonError, read_json, write_json_atomic
from assets.runtime.hardened.config_service import ConfigurationError, ConfigurationService, migrate_configuration, validate_configuration


def legacy(fields=None, **extra):
    data = {"nombre": "Prueba", "campos": fields or [{"dato": "Cedula", "tabuladores": 0}]}
    data.update(extra)
    return data


def test_legacy_migration_preserves_semantics():
    migrated = migrate_configuration(legacy(), fallback_name="x")
    assert migrated["schema_version"] == 2
    assert migrated["campos"][0]["dato"] == "Cedula"
    assert migrated["accion_final"] == "tab"


def test_unknown_label_and_duplicate_rejected(tmp_path):
    with pytest.raises(ConfigurationError, match="desconocida"):
        validate_configuration(legacy([{"dato": "Inventado"}]), source_path="x.json", generation=0)
    with pytest.raises(ConfigurationError, match="duplicado"):
        validate_configuration(legacy([{"dato": "Cedula"}, {"dato": "Cedula"}]), source_path="x.json", generation=0)


@pytest.mark.parametrize("tabs", [-1, 51, "nan"])
def test_tab_limits(tabs):
    with pytest.raises(ConfigurationError):
        validate_configuration(legacy([{"dato": "Cedula", "tabuladores": tabs}]), source_path="x.json", generation=0)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 6.0])
def test_wait_limits(value):
    with pytest.raises(ConfigurationError):
        validate_configuration(legacy([{"dato": "Cedula", "espera_adicional": value}]), source_path="x.json", generation=0)


def test_corrupt_active_is_not_silently_replaced(tmp_path):
    service = ConfigurationService(tmp_path / "configs")
    service.initialize()
    service.active_path.write_text("{bad", encoding="utf-8")
    with pytest.raises((ConfigurationError, AtomicJsonError)):
        service.load_active()


def test_missing_active_form_blocks_writing(tmp_path):
    service = ConfigurationService(tmp_path / "configs")
    service.initialize()
    write_json_atomic(service.active_path, {"activa": "missing.json"}, backup=False)
    with pytest.raises(ConfigurationError, match="no existe"):
        service.load_active()


def test_atomic_write_creates_backup(tmp_path):
    path = tmp_path / "critical.json"
    write_json_atomic(path, {"value": 1}, backup=False)
    write_json_atomic(path, {"value": 2})
    assert read_json(path)["value"] == 2
    assert read_json(path.with_suffix(".json.bak"))["value"] == 1
