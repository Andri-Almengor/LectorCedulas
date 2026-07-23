from __future__ import annotations

import threading
from types import SimpleNamespace

from assets.runtime.hardened.models import FieldAction, FinalAction
from assets.runtime.hardened.production_app import ProductionDesktopApplication


class FakeSlots:
    def __init__(self):
        self.releases = 0

    def release(self):
        self.releases += 1


class FakeSerial:
    def __init__(self):
        self.accepted = []
        self.rejected = []

    def confirm_accepted(self, identity):
        self.accepted.append(identity)

    def confirm_rejected(self, raw, reason):
        self.rejected.append((raw, reason))


def snapshot(generation: int):
    return SimpleNamespace(
        configuration_id="cfg",
        name="Configuracion",
        schema_version=2,
        generation=generation,
        profile="rapida",
        fields=(FieldAction("Cedula", action_after=FinalAction.NONE),),
        final_action=FinalAction.NONE,
    )


def build_app(current_generation: int):
    app = ProductionDesktopApplication.__new__(ProductionDesktopApplication)
    app._configuration_transition_lock = threading.RLock()
    app._processing_slots = FakeSlots()
    app.parsers = SimpleNamespace(
        parse=lambda _raw: SimpleNamespace(
            recognized=True,
            parser_id="CODIGO_CORTO_CI",
            data={
                "TipoCedulaDetectado": "CODIGO_CORTO_CI",
                "Cedula": "119320121",
                "Nombre": "DESCONOCIDO",
                "Apellidos": "DESCONOCIDO",
            },
        )
    )
    app.tse = SimpleNamespace(enrich=lambda data: data)
    app.serial = FakeSerial()
    app.config = SimpleNamespace(load_active=lambda: snapshot(current_generation))
    app.last_error = "Sin errores"
    app._notify_calls = []
    app._log_calls = []
    app._notify = lambda title, message: app._notify_calls.append((title, message))
    app._log = app._log_calls.append
    return app


def test_scan_is_rejected_when_configuration_generation_changed_during_parse():
    app = build_app(current_generation=2)
    enqueued = []
    app._enqueue_validated_scan = lambda *args: enqueued.append(args) or True
    raw = b"119320121"
    identity = object()

    app._process_scan_async(raw, object(), identity, snapshot(1))

    assert not enqueued
    assert app.serial.accepted == []
    assert app.serial.rejected == [(raw, "configuration_changed_during_scan")]
    assert app._processing_slots.releases == 1
    assert any(title == "Configuración cambiada" for title, _ in app._notify_calls)


def test_scan_with_same_generation_reaches_queue_and_confirms_port():
    app = build_app(current_generation=3)
    calls = []
    app._enqueue_validated_scan = lambda raw, data, target, snap: calls.append(
        (raw, data, target, snap.generation)
    ) or True
    raw = b"119320121"
    target = object()
    identity = object()

    app._process_scan_async(raw, target, identity, snapshot(3))

    assert len(calls) == 1
    assert calls[0][0] == raw
    assert calls[0][2] is target
    assert calls[0][3] == 3
    assert app.serial.rejected == []
    assert app.serial.accepted == [identity]
    assert app._processing_slots.releases == 1


def test_invalid_configuration_at_frame_start_is_rejected_without_queueing():
    app = build_app(current_generation=1)
    enqueued = []
    app._enqueue_validated_scan = lambda *args: enqueued.append(args) or True
    raw = b"119320121"

    app._process_scan_async(raw, object(), object(), None)

    assert not enqueued
    assert app.serial.accepted == []
    assert app.serial.rejected == [(raw, "configuration_invalid")]
    assert app._processing_slots.releases == 1
