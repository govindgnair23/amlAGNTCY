from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock


@dataclass(frozen=True)
class StepEventPayload:
    case_id: str
    step_name: str
    message: str
    timestamp: str

    @classmethod
    def create(cls, *, case_id: str, step_name: str, message: str) -> "StepEventPayload":
        timestamp = datetime.now(timezone.utc).isoformat()
        return cls(case_id=case_id, step_name=step_name, message=message, timestamp=timestamp)

    @classmethod
    def from_dict(cls, data: dict) -> "StepEventPayload":
        return cls(
            case_id=str(data.get("case_id", "")),
            step_name=str(data.get("step_name", "")),
            message=str(data.get("message", "")),
            timestamp=str(data.get("timestamp", "")),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "case_id": self.case_id,
            "step_name": self.step_name,
            "message": self.message,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class StepEventEntry:
    entry_id: int
    case_id: str
    step_name: str
    message: str
    timestamp: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "id": self.entry_id,
            "case_id": self.case_id,
            "step_name": self.step_name,
            "message": self.message,
            "timestamp": self.timestamp,
        }


class StepEventCollector:
    def __init__(self, *, case_id: str) -> None:
        self._case_id = case_id
        self._events: list[StepEventPayload] = []

    def emit(self, step_name: str, message: str) -> None:
        self._events.append(
            StepEventPayload.create(
                case_id=self._case_id,
                step_name=step_name,
                message=message,
            )
        )

    def to_payloads(self) -> list[dict[str, str]]:
        return [event.to_dict() for event in self._events]


class StepEventBuffer:
    def __init__(self, max_entries: int = 500) -> None:
        self._entries: deque[StepEventEntry] = deque(maxlen=max_entries)
        self._next_id = 1
        self._lock = Lock()

    def append(self, payload: StepEventPayload) -> StepEventEntry:
        with self._lock:
            entry = StepEventEntry(
                entry_id=self._next_id,
                case_id=payload.case_id,
                step_name=payload.step_name,
                message=payload.message,
                timestamp=payload.timestamp,
            )
            self._next_id += 1
            self._entries.append(entry)
            return entry

    def append_raw(self, *, case_id: str, step_name: str, message: str) -> StepEventEntry:
        payload = StepEventPayload.create(case_id=case_id, step_name=step_name, message=message)
        return self.append(payload)

    def get_since(
        self, *, since_id: int | None = None, case_id: str | None = None
    ) -> list[dict[str, str | int]]:
        with self._lock:
            entries = list(self._entries)
        if since_id is not None:
            entries = [entry for entry in entries if entry.entry_id > since_id]
        if case_id:
            entries = [entry for entry in entries if entry.case_id == case_id]
        return [entry.to_dict() for entry in entries]
