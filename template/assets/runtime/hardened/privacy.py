from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

_CEDULA_RE = re.compile(r"(?<!\d)(\d{1,3})[- ]?(\d{3,4})[- ]?(\d{3,4})(?!\d)")
_TOKEN_RE = re.compile(r"(?i)(token|signature|sig|authorization|apikey|api_key)=([^&\s]+)")
_LONG_DIGITS_RE = re.compile(r"(?<!\d)\d{7,12}(?!\d)")


def mask_identifier(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 4:
        return "***"
    return "*" * max(0, len(digits) - 4) + digits[-4:]


def redact_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        if not parts.scheme or not parts.netloc:
            return value
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:
        return "[URL_REDACTED]"


def redact_text(value: Any) -> str:
    text = str(value)
    text = _TOKEN_RE.sub(r"\1=[REDACTED]", text)
    text = _CEDULA_RE.sub(lambda match: mask_identifier(match.group(0)), text)
    text = _LONG_DIGITS_RE.sub(lambda match: mask_identifier(match.group(0)), text)
    text = re.sub(r"https://[^\s]+", lambda match: redact_url(match.group(0)), text)
    return text


def technical_event(event: str, **fields: Any) -> str:
    safe: dict[str, Any] = {"event": event}
    allowed = {
        "sequence_id",
        "state",
        "reason",
        "port",
        "vid",
        "pid",
        "queue_size",
        "configuration_id",
        "configuration_generation",
        "target_hwnd",
        "target_pid",
        "elapsed_ms",
        "error_type",
        "version",
        "license_id",
        "client_id",
    }
    for key, value in fields.items():
        if key in allowed:
            safe[key] = redact_text(value)
    return json.dumps(safe, ensure_ascii=False, sort_keys=True)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        return True


def build_logger(
    log_dir: str | os.PathLike[str],
    *,
    name: str = "dms_lector",
    max_bytes: int = 2_000_000,
    backups: int = 10,
) -> logging.Logger:
    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger
    handler = logging.handlers.RotatingFileHandler(
        directory / "lector.log",
        maxBytes=max_bytes,
        backupCount=backups,
        encoding="utf-8",
    )
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)sZ %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger
