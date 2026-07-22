import ctypes
import os

from assets.runtime import dms_session_runtime as session


def watch_console_user_switch():
    """Cierra al cambiar usuario en consola, sin afectar sesiones RDP."""
    if os.name != "nt":
        return

    try:
        process_id = ctypes.windll.kernel32.GetCurrentProcessId()
        own_session = ctypes.c_ulong()
        ctypes.windll.kernel32.ProcessIdToSessionId(
            process_id,
            ctypes.byref(own_session),
        )

        initial_active = int(
            ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
        )
        if initial_active == 0xFFFFFFFF:
            return

        # Una aplicación iniciada por RDP no pertenece a la consola física.
        # En ese caso no se usa este detector para evitar un cierre inmediato.
        if initial_active != own_session.value:
            session.log(
                "ℹ️ Supervisor de cambio de usuario de consola omitido en sesión remota."
            )
            return

        mismatches = 0
        while not session.STOP.wait(1.0):
            active_session = int(
                ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
            )
            if (
                active_session != 0xFFFFFFFF
                and active_session != own_session.value
            ):
                mismatches += 1
            else:
                mismatches = 0

            if mismatches >= 2:
                session.shutdown("Windows cambió de usuario o de sesión")
                return
    except Exception as error:
        session.log(
            f"⚠️ No se pudo supervisar la sesión de Windows: {error}"
        )


session._windows_session_watch = watch_console_user_switch
