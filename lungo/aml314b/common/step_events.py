from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock


@dataclass(frozen=True)
class StepEventPayload:
    case_id: str
    investigation_type: str
    transport_lane: str | None
    step_name: str
    message: str
    timestamp: str

    @classmethod
    def create(
        cls,
        *,
        case_id: str,
        investigation_type: str,
        transport_lane: str | None,
        step_name: str,
        message: str,
    ) -> "StepEventPayload":
        timestamp = datetime.now(timezone.utc).isoformat()
        return cls(
            case_id=case_id,
            investigation_type=investigation_type,
            transport_lane=transport_lane,
            step_name=step_name,
            message=message,
            timestamp=timestamp,
        )

    @classmethod
    def from_dict(cls, data: dict) -> "StepEventPayload":
        return cls(
            case_id=str(data.get("case_id", "")),
            investigation_type=str(data.get("investigation_type", "")),
            transport_lane=(
                str(data["transport_lane"])
                if data.get("transport_lane") is not None
                else None
            ),
            step_name=str(data.get("step_name", "")),
            message=str(data.get("message", "")),
            timestamp=str(data.get("timestamp", "")),
        )

    def to_dict(self) -> dict[str, str | None]:
        return {
            "case_id": self.case_id,
            "investigation_type": self.investigation_type,
            "transport_lane": self.transport_lane,
            "step_name": self.step_name,
            "message": self.message,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class StepEventEntry:
    entry_id: int
    case_id: str
    investigation_type: str
    transport_lane: str | None
    step_name: str
    message: str
    timestamp: str

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "id": self.entry_id,
            "case_id": self.case_id,
            "investigation_type": self.investigation_type,
            "transport_lane": self.transport_lane,
            "step_name": self.step_name,
            "message": self.message,
            "timestamp": self.timestamp,
        }


class StepEventCollector:
    def __init__(
        self,
        *,
        case_id: str,
        investigation_type: str,
        transport_lane: str | None = None,
    ) -> None:
        self._case_id = case_id
        self._investigation_type = investigation_type
        self._transport_lane = transport_lane
        self._events: list[StepEventPayload] = []

    def emit(self, step_name: str, message: str) -> None:
        self._events.append(
            StepEventPayload.create(
                case_id=self._case_id,
                investigation_type=self._investigation_type,
                transport_lane=self._transport_lane,
                step_name=step_name,
                message=message,
            )
        )

    def to_payloads(self) -> list[dict[str, str | None]]:
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
                investigation_type=payload.investigation_type,
                transport_lane=payload.transport_lane,
                step_name=payload.step_name,
                message=payload.message,
                timestamp=payload.timestamp,
            )
            self._next_id += 1
            self._entries.append(entry)
            return entry

    def append_raw(
        self,
        *,
        case_id: str,
        investigation_type: str,
        transport_lane: str | None,
        step_name: str,
        message: str,
    ) -> StepEventEntry:
        return self.append(
            StepEventPayload.create(
                case_id=case_id,
                investigation_type=investigation_type,
                transport_lane=transport_lane,
                step_name=step_name,
                message=message,
            )
        )

    def latest_id(self) -> int:
        with self._lock:
            if not self._entries:
                return 0
            return self._entries[-1].entry_id

    def get_since(
        self,
        *,
        since_id: int | None = None,
        case_id: str | None = None,
        investigation_type: str | None = None,
        transport_lane: str | None = None,
    ) -> list[dict[str, str | int | None]]:
        with self._lock:
            entries = list(self._entries)
        if since_id is not None:
            entries = [entry for entry in entries if entry.entry_id > since_id]
        if case_id:
            entries = [entry for entry in entries if entry.case_id == case_id]
        if investigation_type:
            entries = [
                entry
                for entry in entries
                if entry.investigation_type == investigation_type
            ]
        if transport_lane:
            entries = [entry for entry in entries if entry.transport_lane == transport_lane]
        return [entry.to_dict() for entry in entries]
