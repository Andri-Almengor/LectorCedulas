from __future__ import annotations

import os
import time
from pathlib import Path


def state_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    path = base / "DMS" / "LectorCedulas" / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def manual_exit_marker() -> Path:
    return state_root() / "manual_exit.flag"


def mark_manual_exit() -> None:
    marker = manual_exit_marker()
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(str(os.getpid()), encoding="utf-8")
    os.replace(temporary, marker)


def consume_manual_exit() -> bool:
    marker = manual_exit_marker()
    if not marker.exists():
        return False
    try:
        marker.unlink()
    except OSError:
        pass
    return True


def append_supervisor_log(message: str) -> None:
    path = state_root() / "supervisor.log"
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message}\n")
    except OSError:
        pass
