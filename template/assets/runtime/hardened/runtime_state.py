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


def restart_suspension_marker() -> Path:
    return state_root() / "suspend_restart.flag"


def suspend_automatic_restart() -> None:
    marker = restart_suspension_marker()
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(str(time.time()), encoding="utf-8")
    os.replace(temporary, marker)


def resume_automatic_restart() -> None:
    try:
        restart_suspension_marker().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def automatic_restart_suspended(*, max_age_seconds: float = 300.0) -> bool:
    marker = restart_suspension_marker()
    if not marker.exists():
        return False
    try:
        created = float(marker.read_text(encoding="utf-8").strip())
    except Exception:
        created = marker.stat().st_mtime
    if time.time() - created <= max_age_seconds:
        return True
    resume_automatic_restart()
    return False


def append_supervisor_log(message: str) -> None:
    path = state_root() / "supervisor.log"
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message}\n")
    except OSError:
        pass
