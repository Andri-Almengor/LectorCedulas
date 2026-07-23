from __future__ import annotations

from types import SimpleNamespace

from assets.runtime.hardened import production_app as production_module
from assets.runtime.hardened.production_app import ProductionDesktopApplication
from assets.runtime.hardened.runtime_state import (
    automatic_restart_suspended,
    consume_manual_exit,
    mark_manual_exit,
    resume_automatic_restart,
    suspend_automatic_restart,
)
from assets.runtime.hardened.safe_clipboard import SafeClipboardManager


class FakeClipboardBackend:
    def __init__(self, value: str = ""):
        self.value = value
        self.copies: list[str] = []

    def copy(self, text: str) -> None:
        self.value = str(text)
        self.copies.append(self.value)

    def paste(self) -> str:
        return self.value


class FakeClipboardApi:
    def __init__(self, formats):
        self._formats = formats
        self.clear_calls = 0

    def formats(self):
        return self._formats

    def clear(self) -> bool:
        self.clear_calls += 1
        return True


class FakeInstance:
    def __init__(self):
        self.acquire_calls = 0

    def acquire(self):
        self.acquire_calls += 1

    def close(self):
        return None


class FakeConfig:
    def __init__(self):
        self.initialize_calls = 0

    def initialize(self):
        self.initialize_calls += 1

    def load_last_port(self):
        return {"device": "COM3"}


def test_safe_clipboard_restores_original_text():
    backend = FakeClipboardBackend("ORIGINAL")
    api = FakeClipboardApi({13})

    with SafeClipboardManager(backend=backend, api=api) as clipboard:
        assert clipboard.can_modify
        assert clipboard.set_text("ALMENGOR QUIROS")
        assert backend.value == "ALMENGOR QUIROS"

    assert backend.value == "ORIGINAL"
    assert backend.copies[-1] == "ORIGINAL"


def test_safe_clipboard_refuses_non_text_formats():
    backend = FakeClipboardBackend("ORIGINAL")
    api = FakeClipboardApi({13, 49300})

    with SafeClipboardManager(backend=backend, api=api) as clipboard:
        assert not clipboard.can_modify
        assert not clipboard.set_text("NO DEBE COPIARSE")

    assert backend.value == "ORIGINAL"
    assert backend.copies == []


def test_empty_clipboard_is_cleared_after_use():
    backend = FakeClipboardBackend("")
    api = FakeClipboardApi(set())

    with SafeClipboardManager(backend=backend, api=api) as clipboard:
        assert clipboard.set_text("TEMPORAL")

    assert api.clear_calls == 1


def test_manual_exit_marker_is_consumed(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    mark_manual_exit()
    assert consume_manual_exit()
    assert not consume_manual_exit()


def test_restart_suspension_expires_cleanly(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    suspend_automatic_restart()
    assert automatic_restart_suspended()
    resume_automatic_restart()
    assert not automatic_restart_suspended()


def test_manual_exit_calls_marker_before_shutdown(monkeypatch):
    actions: list[str] = []
    monkeypatch.setattr(
        production_module,
        "mark_manual_exit",
        lambda: actions.append("marker"),
    )
    app = ProductionDesktopApplication.__new__(ProductionDesktopApplication)
    app.logger = SimpleNamespace(info=lambda _message: None)
    app.shutdown = lambda: actions.append("shutdown")

    app._request_exit()

    assert actions == ["marker", "shutdown"]


def test_recovery_startup_skips_calibration():
    app = ProductionDesktopApplication.__new__(ProductionDesktopApplication)
    app._recovery_mode = True
    app.instance = FakeInstance()
    app.config = FakeConfig()
    app.last_error = "Sin errores"
    app.logger = SimpleNamespace(info=lambda _message: None)
    app._validate_license = lambda: None
    app._run_calibration_dialog = lambda: (_ for _ in ()).throw(
        AssertionError("No debe calibrar durante recuperación")
    )

    result = app._startup()

    assert result == 0
    assert app.instance.acquire_calls == 1
    assert app.config.initialize_calls == 1
    assert app.last_error == "Proceso recuperado automáticamente"
