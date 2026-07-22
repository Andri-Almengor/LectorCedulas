from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes
from typing import Callable

MUTEX_NAME = r"Global\DMS_LectorCedulas_SingleInstance_v4"
STOP_EVENT_NAME = r"Global\DMS_LectorCedulas_StopEvent_v4"
ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258


class InstanceAlreadyRunning(RuntimeError):
    pass


class InstanceControl:
    def __init__(self, shutdown_callback: Callable[[], None]):
        self.shutdown_callback = shutdown_callback
        self._mutex = None
        self._event = None
        self._watcher: threading.Thread | None = None
        self._closed = threading.Event()

    def acquire(self) -> None:
        if os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateEventW.restype = wintypes.HANDLE
        ctypes.set_last_error(0)
        mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not mutex:
            raise OSError("No se pudo crear el mutex de instancia")
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(mutex)
            raise InstanceAlreadyRunning("La aplicación ya está en ejecución")
        event = kernel32.CreateEventW(None, False, False, STOP_EVENT_NAME)
        if not event:
            kernel32.CloseHandle(mutex)
            raise OSError("No se pudo crear el evento de cierre")
        self._mutex = mutex
        self._event = event
        self._watcher = threading.Thread(target=self._watch, name="DMSStopEvent", daemon=True)
        self._watcher.start()

    def _watch(self) -> None:
        if os.name != "nt" or not self._event:
            return
        kernel32 = ctypes.windll.kernel32
        while not self._closed.is_set():
            result = kernel32.WaitForSingleObject(self._event, 500)
            if result == WAIT_OBJECT_0:
                self.shutdown_callback()
                return
            if result != WAIT_TIMEOUT:
                return

    def close(self) -> None:
        self._closed.set()
        if os.name != "nt":
            return
        kernel32 = ctypes.windll.kernel32
        for handle_name in ("_event", "_mutex"):
            handle = getattr(self, handle_name)
            if handle:
                kernel32.CloseHandle(handle)
                setattr(self, handle_name, None)


def signal_running_instance() -> bool:
    if os.name != "nt":
        return False
    kernel32 = ctypes.windll.kernel32
    EVENT_MODIFY_STATE = 0x0002
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, STOP_EVENT_NAME)
    if not handle:
        return False
    try:
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)
