from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "template"
if str(TEMPLATE) not in sys.path:
    sys.path.insert(0, str(TEMPLATE))

from assets.runtime.hardened.app_runtime import Application


if __name__ == "__main__":
    raise SystemExit(Application(root_dir=TEMPLATE).run())
