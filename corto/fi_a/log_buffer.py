from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock


@dataclass(frozen=True)
class LogEntry:
    entry_id: int
    timestamp: str
    level: str
    logger: str
    message: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "id": self.entry_id,
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger,
            "message": self.message,
        }


class LogBuffer:
    def __init__(self, max_entries: int = 500) -> None:
        self._entries: deque[LogEntry] = deque(maxlen=max_entries)
        self._next_id = 1
        self._lock = Lock()

    def append(self, *, level: str, logger: str, message: str, timestamp: str) -> None:
        with self._lock:
            entry = LogEntry(
                entry_id=self._next_id,
                timestamp=timestamp,
                level=level,
                logger=logger,
                message=message,
            )
            self._next_id += 1
            self._entries.append(entry)

    def get_since(self, since_id: int | None = None) -> list[dict[str, str | int]]:
        with self._lock:
            entries = list(self._entries)
        if since_id is not None:
            entries = [entry for entry in entries if entry.entry_id > since_id]
        return [entry.to_dict() for entry in entries]


class LogBufferHandler(logging.Handler):
    def __init__(self, log_buffer: LogBuffer, logger_prefix: str) -> None:
        super().__init__()
        self._log_buffer = log_buffer
        self._logger_prefix = logger_prefix

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith(self._logger_prefix):
            return
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        self._log_buffer.append(
            level=record.levelname,
            logger=record.name,
            message=record.getMessage(),
            timestamp=timestamp,
        )
