from __future__ import annotations

import json
import zipfile
from pathlib import Path

from tools import release_builder


def test_update_archive_contains_managed_catalog_but_not_client_state(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "repo"
    clients = root / "clientes"
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "updater.py").write_text("print('ok')", encoding="utf-8")

    monkeypatch.setattr(release_builder, "ROOT", root)
    monkeypatch.setattr(release_builder, "CLIENTS", clients)

    def prepare(_client, build_root: Path) -> Path:
        work = build_root / "work"
        (work / "assets").mkdir(parents=True)
        (work / "assets" / "runtime.dat").write_text("runtime", encoding="utf-8")
        (work / "configs" / "formatos").mkdir(parents=True)
        (work / "configs" / "formatos" / "formatos_cedulas.json").write_text(
            json.dumps({"formatos": []}),
            encoding="utf-8",
        )
        (work / "configs" / "formularios").mkdir(parents=True)
        (work / "configs" / "formularios" / "cliente.json").write_text(
            "{}",
            encoding="utf-8",
        )
        (work / "configs" / "sistema").mkdir(parents=True)
        (work / "configs" / "sistema" / "ultimo_com.json").write_text(
            "{}",
            encoding="utf-8",
        )
        (work / "licencia.key").write_text("preservada", encoding="utf-8")
        return work

    def build(work: Path, _script, name, _log, *, console=False) -> Path:
        output = work / "dist" / f"{name}.exe"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"MZ" + b"0" * 2048)
        return output

    monkeypatch.setattr(release_builder, "_prepare_work", prepare)
    monkeypatch.setattr(release_builder, "_build_exe", build)
    monkeypatch.setattr(
        release_builder,
        "_ensure_keys",
        lambda _name: (tmp_path / "key-a", tmp_path / "key-b"),
    )
    monkeypatch.setattr(
        release_builder,
        "sign_manifest",
        lambda payload, _path: {"payload": payload, "signature": "test"},
    )
    monkeypatch.setattr(release_builder, "_generate_sbom", lambda *args: False)

    archive = Path(
        release_builder.make_update_zip(
            release_builder.VERSION,
            str(tmp_path / "out"),
        )
    )

    with zipfile.ZipFile(archive) as handle:
        names = set(handle.namelist())

    assert "payload/configs/formatos/formatos_cedulas.json" in names
    assert "payload/configs/formularios/cliente.json" not in names
    assert "payload/configs/sistema/ultimo_com.json" not in names
    assert "payload/licencia.key" not in names
    assert "payload/LectorCedulasDMS.exe" in names
    assert "payload/crear_configuracion.exe" in names
