import time

from assets.runtime import dms_session_runtime as session
from assets.runtime import lector_core as core


SERIAL_POLL_SECONDS = 0.025


def wait_serial_silent(serial_port, quiet_seconds=0.35, timeout=2.0):
    start = time.monotonic()
    quiet_start = time.monotonic()
    while not session.STOP.is_set() and time.monotonic() - start < timeout:
        try:
            waiting = serial_port.in_waiting
            if waiting:
                serial_port.read(waiting)
                quiet_start = time.monotonic()
            elif time.monotonic() - quiet_start >= quiet_seconds:
                return
        except Exception:
            return
        if session.STOP.wait(SERIAL_POLL_SECONDS):
            return


def read_serial_buffer(
    serial_port,
    timeout_total=3.0,
    max_bytes=None,
    idle_seconds=None,
):
    max_bytes = max_bytes or core.READ_MAX_BYTES
    idle_seconds = idle_seconds or core.READ_IDLE_SECONDS
    data = bytearray()
    start = time.monotonic()
    last_data = None

    while not session.STOP.is_set() and time.monotonic() - start < timeout_total:
        try:
            waiting = serial_port.in_waiting
            if waiting:
                chunk = serial_port.read(waiting)
                if chunk:
                    data.extend(chunk)
                    last_data = time.monotonic()
                    if len(data) > max_bytes:
                        break
            elif data and last_data and time.monotonic() - last_data >= idle_seconds:
                if session.STOP.wait(0.06):
                    break
                if not serial_port.in_waiting:
                    break
        except Exception:
            break

        if session.STOP.wait(SERIAL_POLL_SECONDS):
            break

    return bytes(data)


def port_responds(port, callback=None, seconds=3):
    if not port or session.STOP.is_set():
        return False
    try:
        if callback:
            callback(f"🔁 Probando último puerto guardado: {port}... pase la cédula")
        with core.serial.Serial(port, 9600, timeout=0.25) as serial_port:
            serial_port.reset_input_buffer()
            data = bytearray()
            start = time.monotonic()
            while not session.STOP.is_set() and time.monotonic() - start < seconds:
                waiting = serial_port.in_waiting
                if waiting:
                    data.extend(serial_port.read(waiting))
                    if len(data) >= 100 or data.endswith(b"\r\n"):
                        if callback:
                            callback(f"✅ {port} respondió correctamente")
                        return True
                if session.STOP.wait(SERIAL_POLL_SECONDS):
                    break
        return False
    except Exception as error:
        if callback and not session.STOP.is_set():
            callback(f"⚠️ {port} no disponible: {error}")
        return False


def find_reader(callback):
    for device in core.serial.tools.list_ports.comports():
        if session.STOP.is_set():
            return None
        port = device.device
        callback(f"🧪 {port} - Pase la cédula")
        try:
            with core.serial.Serial(port, 9600, timeout=0.25) as serial_port:
                serial_port.reset_input_buffer()
                data = bytearray()
                start = time.monotonic()
                while not session.STOP.is_set() and time.monotonic() - start < 6:
                    waiting = serial_port.in_waiting
                    if waiting:
                        data.extend(serial_port.read(waiting))
                        if len(data) >= 100:
                            callback(f"✅ {port} detectado")
                            return port
                    if session.STOP.wait(SERIAL_POLL_SECONDS):
                        return None
        except Exception as error:
            callback(f"❌ {port} falló: {error}")

    if not session.STOP.is_set():
        callback("🔴 No se detectó lector QR.")
    return None


def write_form(data, configuration):
    """Escribe con pausas controladas para no saturar la aplicación destino."""
    for field in configuration.get("campos", []):
        if session.STOP.is_set():
            return

        core.safe_tab(field.get("tabuladores", 0))
        label = (field.get("dato") or "").strip()
        core.write_field_value(data.get(label, ""), is_critical=False)

        if session.STOP.wait(0.08):
            return
        core.pyautogui.press("tab")
        if session.STOP.wait(core.BETWEEN_FIELDS):
            return


def serial_listener(port, load_configuration):
    try:
        with core.serial.Serial(port, 9600, timeout=0.25) as serial_port:
            session.set_active_serial(serial_port)
            serial_port.reset_input_buffer()
            wait_serial_silent(serial_port)
            session.log(f"ℹ️ Lector activo en {port} con modo de bajo consumo.")

            while not session.STOP.is_set():
                raw = read_serial_buffer(serial_port)
                if session.STOP.is_set():
                    break
                if not raw:
                    continue

                invalid, reason = core._buffer_parece_mezclado_o_incompleto(raw)
                if invalid:
                    core.guardar_raw_no_reconocido(raw, reason)
                    wait_serial_silent(serial_port)
                    continue

                now = time.monotonic()
                with core._processing_lock:
                    if now - core._last_read_ts < core.COOLDOWN_SECONDS:
                        wait_serial_silent(serial_port)
                        continue
                    core._last_read_ts = now

                try:
                    data = core.parse_cedula_unificada(raw)
                    session.log(data)
                    if not core._is_probably_valid_person(data):
                        core.guardar_raw_no_reconocido(
                            raw,
                            "datos_no_confiables_o_documento_no_soportado",
                        )
                        continue

                    configuration = load_configuration()
                    if configuration:
                        serial_port.reset_input_buffer()
                        if session.STOP.wait(0.12):
                            break
                        write_form(data, configuration)
                        if session.STOP.wait(0.18):
                            break
                        serial_port.reset_input_buffer()
                        wait_serial_silent(serial_port)
                except Exception as error:
                    if not session.STOP.is_set():
                        session.log(f"⚠️ Error procesando lectura: {error}")
    except Exception as error:
        if not session.STOP.is_set():
            session.log(f"❌ Error del puerto serial {port}: {error}")
    finally:
        session.set_active_serial(None)
