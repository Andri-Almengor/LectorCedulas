from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "template"
if str(TEMPLATE) not in sys.path:
    sys.path.insert(0, str(TEMPLATE))

from assets.runtime.hardened.process_supervisor import run_entrypoint  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(run_entrypoint(TEMPLATE))
