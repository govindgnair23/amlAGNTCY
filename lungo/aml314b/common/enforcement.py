from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union
import logging

from aml314b.common.schemas import (
    B314Request,
    B314Response,
    CollaborationContribution,
    CollaborationSessionRequest,
    DiscoveryRequest,
    DiscoveryResponse,
)

DEFAULT_LOGGER_NAME = "lungo.aml314b.enforcement"

Direction = Literal[
    "outbound_request",
    "inbound_request",
    "outbound_response",
    "inbound_response",
]
MessageType = Literal[
    "314b_request",
    "314b_response",
    "collaboration_request",
    "collaboration_contribution",
    "discovery_request",
    "discovery_response",
]
Message = Union[
    B314Request,
    B314Response,
    CollaborationContribution,
    CollaborationSessionRequest,
    DiscoveryRequest,
    DiscoveryResponse,
]


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

    def enforce_outbound_discovery_request(self, request: DiscoveryRequest) -> DiscoveryRequest:
        return self._enforce("outbound_request", "discovery_request", request)

    def enforce_inbound_discovery_request(self, request: DiscoveryRequest) -> DiscoveryRequest:
        return self._enforce("inbound_request", "discovery_request", request)

    def enforce_outbound_discovery_response(
        self, response: DiscoveryResponse, *, case_id: str | None = None
    ) -> DiscoveryResponse:
        return self._enforce(
            "outbound_response",
            "discovery_response",
            response,
            case_id=case_id,
        )

    def enforce_inbound_discovery_response(
        self, response: DiscoveryResponse, *, case_id: str | None = None
    ) -> DiscoveryResponse:
        return self._enforce(
            "inbound_response",
            "discovery_response",
            response,
            case_id=case_id,
        )

    def enforce_outbound_collaboration_request(
        self, request: CollaborationSessionRequest
    ) -> CollaborationSessionRequest:
        return self._enforce("outbound_request", "collaboration_request", request)

    def enforce_inbound_collaboration_request(
        self, request: CollaborationSessionRequest
    ) -> CollaborationSessionRequest:
        return self._enforce("inbound_request", "collaboration_request", request)

    def enforce_outbound_collaboration_contribution(
        self,
        contribution: CollaborationContribution,
        *,
        case_id: str | None = None,
    ) -> CollaborationContribution:
        return self._enforce(
            "outbound_response",
            "collaboration_contribution",
            contribution,
            case_id=case_id,
        )

    def enforce_inbound_collaboration_contribution(
        self,
        contribution: CollaborationContribution,
        *,
        case_id: str | None = None,
    ) -> CollaborationContribution:
        return self._enforce(
            "inbound_response",
            "collaboration_contribution",
            contribution,
            case_id=case_id,
        )

    def _enforce(
        self,
        direction: Direction,
        message_type: MessageType,
        message: Message,
        *,
        case_id: str | None = None,
    ):
        validated = self._validate(message_type, message)
        decision = self._apply_rules(validated)
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
        validators = {
            "314b_request": B314Request,
            "314b_response": B314Response,
            "collaboration_request": CollaborationSessionRequest,
            "collaboration_contribution": CollaborationContribution,
            "discovery_request": DiscoveryRequest,
            "discovery_response": DiscoveryResponse,
        }
        return validators[message_type].model_validate(message.model_dump())

    def _apply_rules(self, message: Message) -> EnforcementDecision:
        if isinstance(message, B314Request):
            if message.purpose != "AML_314B":
                return EnforcementDecision(False, "purpose must be AML_314B")
            if not message.entities:
                return EnforcementDecision(False, "entities must be non-empty")
            return EnforcementDecision(True, "request allowed")
        if isinstance(message, B314Response):
            if message.usage_constraints.purpose != "AML_314B":
                return EnforcementDecision(False, "usage_constraints.purpose must be AML_314B")
            if not message.in_reply_to.strip():
                return EnforcementDecision(False, "in_reply_to must be non-empty")
            return EnforcementDecision(True, "response allowed")
        if isinstance(message, DiscoveryRequest):
            if not message.requestor_institution_id.strip():
                return EnforcementDecision(False, "requestor_institution_id must be non-empty")
            if not message.target_institution_id.strip():
                return EnforcementDecision(False, "target_institution_id must be non-empty")
            return EnforcementDecision(True, "discovery request allowed")
        if isinstance(message, CollaborationSessionRequest):
            if not message.originating_institution_id.strip():
                return EnforcementDecision(False, "originating_institution_id must be non-empty")
            if not message.participant_institution_ids:
                return EnforcementDecision(False, "participant_institution_ids must be non-empty")
            return EnforcementDecision(True, "collaboration request allowed")
        if isinstance(message, CollaborationContribution):
            if not message.session_id.strip():
                return EnforcementDecision(False, "session_id must be non-empty")
            if message.sequence_number < 1:
                return EnforcementDecision(False, "sequence_number must be greater than zero")
            return EnforcementDecision(True, "collaboration contribution allowed")
        if not message.in_reply_to.strip():
            return EnforcementDecision(False, "in_reply_to must be non-empty")
        return EnforcementDecision(True, "discovery response allowed")
