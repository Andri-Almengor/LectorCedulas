from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


class AtomicJsonError(RuntimeError):
    pass


def read_json(path: str | os.PathLike[str], *, default: Any = None, required: bool = False) -> Any:
    target = Path(path)
    try:
        with target.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        if required:
            raise AtomicJsonError(f"No existe el archivo requerido: {target}")
        return default
    except (OSError, json.JSONDecodeError) as exc:
        raise AtomicJsonError(f"No se pudo leer JSON válido de {target}: {exc}") from exc


def write_json_atomic(
    path: str | os.PathLike[str],
    data: Any,
    *,
    backup: bool = True,
    mode: int = 0o600,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup and target.exists():
        backup_path = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, backup_path)
        try:
            os.chmod(backup_path, mode)
        except OSError:
            pass

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, mode)
        except OSError:
            pass
        os.replace(temporary, target)
        try:
            directory_fd = os.open(str(target.parent), os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
