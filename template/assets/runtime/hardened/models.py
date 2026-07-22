from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReaderState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    DISCOVERING = "DISCOVERING"
    CONNECTING = "CONNECTING"
    READY = "READY"
    READING = "READING"
    PROCESSING = "PROCESSING"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"
    STOPPING = "STOPPING"


class JobState(str, Enum):
    QUEUED = "QUEUED"
    WAITING_TARGET = "WAITING_TARGET"
    WRITING = "WRITING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class EmptyPolicy(str, Enum):
    PRESERVE = "preserve"
    CLEAR = "clear"
    DEFAULT = "default"
    CANCEL = "cancel"


class FinalAction(str, Enum):
    NONE = "none"
    TAB = "tab"
    ENTER = "enter"
    SHIFT_TAB = "shift_tab"
    CUSTOM = "custom"


class ValidationType(str, Enum):
    NONE = "none"
    STRICT_TEXT = "strict_text"
    CEDULA = "cedula"
    DATE = "date"
    SEX = "sex"
    NAME = "name"


@dataclass(frozen=True, slots=True)
class TargetWindow:
    hwnd: int
    pid: int
    root_hwnd: int
    title: str = ""
    class_name: str = ""

    @property
    def valid_identity(self) -> bool:
        return self.hwnd > 0 and self.pid > 0 and self.root_hwnd > 0


@dataclass(frozen=True, slots=True)
class FieldAction:
    label: str
    tabs_before: int = 0
    empty_policy: EmptyPolicy = EmptyPolicy.PRESERVE
    default_value: str = ""
    replace_existing: bool = False
    validation: ValidationType = ValidationType.NONE
    normalized_compare: bool = False
    extra_wait: float = 0.0
    action_after: FinalAction = FinalAction.TAB
    custom_action: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WriteProfile:
    name: str
    initial_delay: float
    focus_timeout: float
    tab_delay: float
    clipboard_delay: float
    post_paste_delay: float
    verify_timeout: float
    between_fields: float
    attempts: int


@dataclass(slots=True)
class WriteResult:
    success: bool
    state: str
    fields_total: int
    fields_written: int
    fields_verified: int
    elapsed_ms: float
    reason: str = ""
    per_field_ms: list[float] = field(default_factory=list)


@dataclass(slots=True)
class ScanJob:
    sequence_id: int
    created_at_utc: datetime
    raw_sha256: str
    data: Mapping[str, Any]
    configuration_id: str
    configuration_name: str
    configuration_version: int
    configuration_generation: int
    write_profile: str
    target: TargetWindow
    fields: Sequence[FieldAction]
    final_action: FinalAction
    state: JobState = JobState.QUEUED
    attempts: int = 0
    cancellation_reason: str = ""
    failure_reason: str = ""

    def technical_summary(self) -> dict[str, Any]:
        return {
            "sequence_id": self.sequence_id,
            "created_at_utc": self.created_at_utc.isoformat(),
            "raw_sha256_prefix": self.raw_sha256[:12],
            "configuration_id": self.configuration_id,
            "configuration_generation": self.configuration_generation,
            "write_profile": self.write_profile,
            "target_hwnd": self.target.hwnd,
            "target_pid": self.target.pid,
            "state": self.state.value,
            "attempts": self.attempts,
        }
