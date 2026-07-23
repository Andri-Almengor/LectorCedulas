from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from .crash_diagnostics import install_crash_diagnostics
from .production_app import ProductionDesktopApplication
from .runtime_state import append_supervisor_log, consume_manual_exit

WORKER_ARG = "--dms-worker"
RECOVERY_ARG = "--dms-recovery"
_SUPERVISOR_MUTEX = r"Global\DMS_LectorCedulas_Supervisor_v1"
_ERROR_ALREADY_EXISTS = 183


class _SupervisorMutex:
    def __init__(self) -> None:
        self.handle = None
        self.kernel32 = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel32.CreateMutexW.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        self.handle = self.kernel32.CreateMutexW(None, False, _SUPERVISOR_MUTEX)
        if not self.handle:
            return False
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None
            return False
        return True

    def close(self) -> None:
        if self.handle and self.kernel32:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


def _application_root(root_dir: str | os.PathLike[str] | None) -> Path:
    if root_dir is not None:
        return Path(root_dir)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(sys.argv[0]).resolve().parent


def _worker_command(*, recovery: bool) -> list[str]:
    args = [WORKER_ARG]
    if recovery:
        args.append(RECOVERY_ARG)
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, str(Path(sys.argv[0]).resolve()), *args]


def run_worker(root_dir: str | os.PathLike[str] | None, *, recovery: bool) -> int:
    root = _application_root(root_dir)
    install_crash_diagnostics(root)
    app = ProductionDesktopApplication(root_dir=root, recovery_mode=recovery)
    return app.run()


def supervise(root_dir: str | os.PathLike[str] | None = None) -> int:
    mutex = _SupervisorMutex()
    if not mutex.acquire():
        return 0
    consume_manual_exit()
    recovery = False
    restart_times: list[float] = []
    try:
        while True:
            command = _worker_command(recovery=recovery)
            append_supervisor_log(f"worker_start recovery={int(recovery)}")
            try:
                process = subprocess.Popen(command, cwd=_application_root(root_dir))
                exit_code = int(process.wait())
            except Exception as exc:
                exit_code = -1
                append_supervisor_log(f"worker_launch_failed type={type(exc).__name__}")

            if consume_manual_exit():
                append_supervisor_log(f"manual_exit code={exit_code}")
                return 0
            if exit_code in {2, 3}:
                append_supervisor_log(f"startup_exit code={exit_code}")
                return exit_code

            now = time.monotonic()
            restart_times = [value for value in restart_times if now - value <= 60.0]
            restart_times.append(now)
            delay = 1.0 if len(restart_times) <= 3 else min(15.0, float(len(restart_times) * 2))
            append_supervisor_log(f"unexpected_exit code={exit_code} restart_in={delay:.1f}")
            time.sleep(delay)
            recovery = True
    finally:
        mutex.close()


def run_entrypoint(root_dir: str | os.PathLike[str] | None = None) -> int:
    arguments = set(sys.argv[1:])
    if WORKER_ARG in arguments:
        return run_worker(root_dir, recovery=RECOVERY_ARG in arguments)
    return supervise(root_dir)
