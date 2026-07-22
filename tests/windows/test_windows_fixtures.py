from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.windows


def test_windows_fixture_files_exist():
    root = Path(__file__).resolve().parent
    assert (root / "tk_form_app.py").is_file()
    assert (root / "fixtures" / "form.html").is_file()
    assert (root / "fixtures" / "WinFormsTestApp.cs").is_file()


@pytest.mark.skipif(os.name != "nt" or not os.environ.get("DMS_INTERACTIVE_DESKTOP"), reason="requiere escritorio Windows interactivo")
def test_interactive_desktop_placeholder():
    assert os.name == "nt"
