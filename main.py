from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "template"
if str(TEMPLATE) not in sys.path:
    sys.path.insert(0, str(TEMPLATE))

from assets.runtime.hardened.desktop_app import DesktopApplication  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(DesktopApplication(root_dir=TEMPLATE).run())
