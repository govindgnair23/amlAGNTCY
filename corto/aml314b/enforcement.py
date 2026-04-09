from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union
import logging
import re

from aml314b.schemas import B314Request, B314Response

DEFAULT_LOGGER_NAME = "corto.aml314b.enforcement"

Direction = Literal[
    "outbound_request",
    "inbound_request",
    "outbound_response",
    "inbound_response",
]
MessageType = Literal["314b_request", "314b_response"]
Message = Union[B314Request, B314Response]

SSN_PATTERNS = (
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b\d{9}\b"),
)


@dataclass
class EnforcementDecision:
    allowed: bool
    reason: str


@dataclass
class EnforcementEvent:
    direction: Direction
    message_type: MessageType
    message_id: str
    case_id: str
    decision: EnforcementDecision


class PlaceholderEnforcementLayer:
    """Static schema enforcement plus simple policy placeholder rules."""

    def __init__(self, *, logger_name: str = DEFAULT_LOGGER_NAME) -> None:
        self._events: list[EnforcementEvent] = []
        self._logger = logging.getLogger(logger_name)

    def get_events(self) -> list[EnforcementEvent]:
        return list(self._events)

    def enforce_outbound_request(self, request: B314Request) -> B314Request:
        return self._enforce("outbound_request", "314b_request", request)

    def enforce_inbound_request(self, request: B314Request) -> B314Request:
        return self._enforce("inbound_request", "314b_request", request)

    def enforce_outbound_response(
        self, response: B314Response, *, case_id: str | None = None
    ) -> B314Response:
        return self._enforce("outbound_response", "314b_response", response, case_id=case_id)

    def enforce_inbound_response(
        self, response: B314Response, *, case_id: str | None = None
    ) -> B314Response:
        return self._enforce("inbound_response", "314b_response", response, case_id=case_id)

    def _enforce(
        self,
        direction: Direction,
        message_type: MessageType,
        message: Message,
        *,
        case_id: str | None = None,
    ):
        validated = self._validate(message_type, message)
        decision = self._apply_rules(message_type, validated)
        resolved_case_id = case_id or getattr(validated, "case_id", "unknown")
        event = EnforcementEvent(
            direction=direction,
            message_type=message_type,
            message_id=validated.message_id,
            case_id=resolved_case_id,
            decision=decision,
        )
        self._events.append(event)
        self._logger.info(
            "enforcement direction=%s type=%s case_id=%s message_id=%s allowed=%s reason=%s",
            event.direction,
            event.message_type,
            event.case_id,
            event.message_id,
            event.decision.allowed,
            event.decision.reason,
        )
        if not decision.allowed:
            raise ValueError(f"Message blocked by placeholder enforcement: {decision.reason}")
        return validated

    def _validate(self, message_type: MessageType, message: Message) -> Message:
        if message_type == "314b_request":
            return B314Request.model_validate(message.model_dump())
        return B314Response.model_validate(message.model_dump())

    def _apply_rules(self, message_type: MessageType, message: Message) -> EnforcementDecision:
        if message_type == "314b_request":
            request = message  # type: ignore[assignment]
            if request.purpose != "AML_314B":
                return EnforcementDecision(False, "purpose must be AML_314B")
            if not request.case_id.strip():
                return EnforcementDecision(False, "case_id must be non-empty")
            if not request.entities:
                return EnforcementDecision(False, "entities must be non-empty")
            return EnforcementDecision(True, "request allowed")

        response = message  # type: ignore[assignment]
        if response.usage_constraints.purpose != "AML_314B":
            return EnforcementDecision(False, "usage_constraints.purpose must be AML_314B")
        if not response.in_reply_to.strip():
            return EnforcementDecision(False, "in_reply_to must be non-empty")
        if not response.summary.strip():
            return EnforcementDecision(False, "summary must be non-empty")
        for pattern in SSN_PATTERNS:
            if pattern.search(response.summary):
                return EnforcementDecision(False, "summary contains SSN-like pattern")
        return EnforcementDecision(True, "response allowed")
