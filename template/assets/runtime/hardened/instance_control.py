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


def _kernel32_api():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateEventW.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.OpenEventW.restype = wintypes.HANDLE
    kernel32.SetEvent.argtypes = [wintypes.HANDLE]
    kernel32.SetEvent.restype = wintypes.BOOL
    return kernel32


class InstanceControl:
    def __init__(self, shutdown_callback: Callable[[], None]):
        self.shutdown_callback = shutdown_callback
        self._mutex = None
        self._event = None
        self._watcher: threading.Thread | None = None
        self._closed = threading.Event()
        self._lock = threading.RLock()
        self._kernel32 = None

    def acquire(self) -> None:
        if os.name != "nt":
            return
        kernel32 = _kernel32_api()
        ctypes.set_last_error(0)
        mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not mutex:
            raise OSError(ctypes.get_last_error(), "No se pudo crear el mutex de instancia")
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(mutex)
            raise InstanceAlreadyRunning("La aplicación ya está en ejecución")
        event = kernel32.CreateEventW(None, False, False, STOP_EVENT_NAME)
        if not event:
            kernel32.CloseHandle(mutex)
            raise OSError(ctypes.get_last_error(), "No se pudo crear el evento de cierre")
        with self._lock:
            self._kernel32 = kernel32
            self._mutex = mutex
            self._event = event
        self._watcher = threading.Thread(target=self._watch, name="DMSStopEvent", daemon=True)
        self._watcher.start()

    def _watch(self) -> None:
        with self._lock:
            kernel32 = self._kernel32
            event = self._event
        if os.name != "nt" or kernel32 is None or not event:
            return
        while not self._closed.is_set():
            result = int(kernel32.WaitForSingleObject(event, 500))
            if result == WAIT_OBJECT_0:
                self.shutdown_callback()
                return
            if result != WAIT_TIMEOUT:
                return

    def close(self) -> None:
        self._closed.set()
        if os.name != "nt":
            return
        with self._lock:
            kernel32 = self._kernel32
            handles = (self._event, self._mutex)
            self._event = None
            self._mutex = None
        if kernel32 is None:
            return
        for handle in handles:
            if handle:
                kernel32.CloseHandle(handle)


def signal_running_instance() -> bool:
    if os.name != "nt":
        return False
    kernel32 = _kernel32_api()
    event_modify_state = 0x0002
    handle = kernel32.OpenEventW(event_modify_state, False, STOP_EVENT_NAME)
    if not handle:
        return False
    try:
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)
