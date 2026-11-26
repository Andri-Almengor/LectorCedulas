"""No se permite confundir la guía externa TSE con verificación en el lector."""
from __future__ import annotations

import ast
from pathlib import Path

from template.assets.runtime.hardened.idc_official_flow import (
    OFFICIAL_GUIDE_NOTICE,
    OFFICIAL_GUIDE_PRIVACY,
    OFFICIAL_GUIDE_STEPS,
    OFFICIAL_TSE_IDC_URL,
)


def test_guide_is_only_manual_external_workflow():
    assert OFFICIAL_TSE_IDC_URL == "https://www.tse.go.cr/idc/"
    assert len(OFFICIAL_GUIDE_STEPS) == 4
    assert "Verificador IDC oficial" in " ".join(OFFICIAL_GUIDE_STEPS)
    assert "manualmente" in " ".join(OFFICIAL_GUIDE_STEPS)
    assert "NO verifica criptográficamente" in OFFICIAL_GUIDE_NOTICE
    assert "No tome ni conserve fotografías" in OFFICIAL_GUIDE_PRIVACY
    assert "No retenga el teléfono" in OFFICIAL_GUIDE_PRIVACY


def test_desktop_panel_has_external_guide_not_identity_automation():
    root = Path(__file__).resolve().parents[2]
    source = (root / "template/assets/runtime/hardened/desktop_ui.py").read_text(
        encoding="utf-8"
    )
    parsed = ast.parse(source)
    names = {
        node.name for node in ast.walk(parsed)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "run_official_idc_guide" in names
    assert "run_control_panel" in names
    assert 'text="Guía IDC oficial"' in source
    assert "webbrowser.open(OFFICIAL_TSE_IDC_URL)" in source
    assert "verified_identity = True" not in source
