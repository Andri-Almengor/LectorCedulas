from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
import traceback
from pathlib import Path

_CRASH_HANDLE = None


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def install_crash_diagnostics(root_dir: str | os.PathLike[str]) -> None:
    """Registra fallos Python y nativos en archivos persistentes."""

    global _CRASH_HANDLE
    diagnostics = Path(root_dir) / "diagnosticos"
    diagnostics.mkdir(parents=True, exist_ok=True)
    native_path = diagnostics / "native_crash.log"
    python_path = diagnostics / "python_crash.log"

    try:
        _CRASH_HANDLE = native_path.open("a", encoding="utf-8", buffering=1)
        _CRASH_HANDLE.write(f"\n[{_timestamp()}] worker_started pid={os.getpid()}\n")
        faulthandler.enable(file=_CRASH_HANDLE, all_threads=True)
    except Exception:
        _CRASH_HANDLE = None

    previous_hook = sys.excepthook

    def write_exception(kind: str, exc_type, exc_value, exc_tb) -> None:
        try:
            with python_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\n[{_timestamp()}] {kind} pid={os.getpid()}\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=handle)
        except Exception:
            pass

    def system_hook(exc_type, exc_value, exc_tb) -> None:
        write_exception("unhandled_main_exception", exc_type, exc_value, exc_tb)
        previous_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = system_hook

    if hasattr(threading, "excepthook"):
        previous_thread_hook = threading.excepthook

        def thread_hook(args) -> None:
            write_exception(
                f"unhandled_thread_exception name={getattr(args.thread, 'name', '')}",
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
            )
            previous_thread_hook(args)

        threading.excepthook = thread_hook
