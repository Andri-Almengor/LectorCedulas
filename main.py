from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "template"
if str(TEMPLATE) not in sys.path:
    sys.path.insert(0, str(TEMPLATE))

from assets.runtime.hardened.reliable_app import ReliableDesktopApplication  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(ReliableDesktopApplication(root_dir=TEMPLATE).run())
