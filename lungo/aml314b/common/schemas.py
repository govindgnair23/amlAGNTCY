from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from aml314b.common.channeling import InvestigationType
from aml314b.common.probing import CandidateResolutionSource


RequestPurpose = Literal["AML_314B"]
RequestedArtifact = Literal["MATCH_ONLY", "BOUNDED_CONTEXT"]
MatchType = Literal["NO_MATCH", "POTENTIAL_MATCH", "CONFIRMED_MATCH"]
RetentionPolicy = Literal["case_lifetime"]
DiscoveryDecision = Literal["ACCEPT", "DECLINE"]
CollaborationParticipantRole = Literal["ORIGINATOR", "RESPONDER"]


class TimeWindow(BaseModel):
    start: datetime
    end: datetime

    @field_validator("end")
    @classmethod
    def validate_window(cls, end: datetime, info):
        start = info.data.get("start")
        if start and end < start:
            raise ValueError("time_window.end must be greater than or equal to start")
        return end


class UsageConstraints(BaseModel):
    purpose: RequestPurpose = "AML_314B"
    retention: RetentionPolicy = "case_lifetime"


class B314Request(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    case_id: str
    purpose: RequestPurpose = "AML_314B"
    entities: list[str]
    time_window: TimeWindow
    activity_summary: str | None = None
    requested_artifacts: list[RequestedArtifact] = Field(
        default_factory=lambda: ["MATCH_ONLY", "BOUNDED_CONTEXT"]
    )

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, case_id: str) -> str:
        if not case_id.strip():
            raise ValueError("case_id must be non-empty")
        return case_id

    @field_validator("entities")
    @classmethod
    def validate_entities(cls, entities: list[str]) -> list[str]:
        cleaned = [entity.strip() for entity in entities if entity and entity.strip()]
        if not cleaned:
            raise ValueError("entities must contain at least one identifier")
        return cleaned


class B314Response(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    in_reply_to: str
    match_type: MatchType
    summary: str
    usage_constraints: UsageConstraints = Field(default_factory=UsageConstraints)
    responded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, summary: str) -> str:
        bounded = summary.strip()
        if not bounded:
            raise ValueError("summary must be non-empty")
        return bounded[:500]


class DiscoveryRequest(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    requestor_institution_id: str
    target_institution_id: str
    investigation_type: InvestigationType
    transport_lane: str | None = None
    case_id: str
    entity_id: str
    entity_name: str
    case_context: str
    time_window: TimeWindow

    @field_validator(
        "requestor_institution_id",
        "target_institution_id",
        "case_id",
        "entity_id",
        "entity_name",
        "case_context",
    )
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{info.field_name} must be non-empty")
        return cleaned

    @field_validator("transport_lane")
    @classmethod
    def validate_transport_lane(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("transport_lane must be non-empty when provided")
        return cleaned


class DiscoveryResponse(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    in_reply_to: str
    responder_institution_id: str
    investigation_type: InvestigationType
    transport_lane: str | None = None
    case_id: str
    entity_id: str
    decision: DiscoveryDecision
    reason: str

    @field_validator(
        "in_reply_to",
        "responder_institution_id",
        "case_id",
        "entity_id",
        "reason",
    )
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{info.field_name} must be non-empty")
        return cleaned[:500]

    @field_validator("transport_lane")
    @classmethod
    def validate_response_transport_lane(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("transport_lane must be non-empty when provided")
        return cleaned


class DiscoveryAggregateResult(BaseModel):
    discovery_session_id: str
    investigation_type: InvestigationType
    transport_lane: str | None = None
    case_id: str
    entity_id: str
    entity_name: str
    candidate_institutions: list[str]
    candidate_response_count: int
    candidate_resolution_source: CandidateResolutionSource
    accepted_institutions: list[str]
    declined_institutions: list[str]
    response_count: int
    responses: list[DiscoveryResponse]


class CollaborationParticipant(BaseModel):
    institution_id: str
    display_name: str
    role: CollaborationParticipantRole

    @field_validator("institution_id", "display_name")
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{info.field_name} must be non-empty")
        return cleaned


class CollaborationSessionRequest(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    investigation_type: InvestigationType
    transport_lane: str | None = None
    case_id: str
    entity_id: str
    entity_name: str
    originating_institution_id: str
    participant_institution_ids: list[str]
    case_context: str
    accepted_institutions: list[str]

    @field_validator(
        "session_id",
        "case_id",
        "entity_id",
        "entity_name",
        "originating_institution_id",
        "case_context",
    )
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{info.field_name} must be non-empty")
        return cleaned

    @field_validator("participant_institution_ids")
    @classmethod
    def validate_institution_ids(cls, value: list[str], info) -> list[str]:
        cleaned = [item.strip().upper() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError(f"{info.field_name} must contain at least one institution")
        return cleaned

    @field_validator("accepted_institutions")
    @classmethod
    def validate_accepted_institutions(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item and item.strip()]

    @field_validator("transport_lane")
    @classmethod
    def validate_session_transport_lane(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("transport_lane must be non-empty when provided")
        return cleaned


class CollaborationContribution(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    investigation_type: InvestigationType
    transport_lane: str | None = None
    case_id: str
    institution_id: str
    contribution: str
    sequence_number: int

    @field_validator("session_id", "case_id", "institution_id", "contribution")
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{info.field_name} must be non-empty")
        if info.field_name == "contribution":
            return cleaned[:500]
        return cleaned

    @field_validator("sequence_number")
    @classmethod
    def validate_sequence_number(cls, value: int) -> int:
        if value < 1:
            raise ValueError("sequence_number must be greater than zero")
        return value

    @field_validator("transport_lane")
    @classmethod
    def validate_contribution_transport_lane(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("transport_lane must be non-empty when provided")
        return cleaned


class CollaborationSessionResult(BaseModel):
    session_id: str
    investigation_type: InvestigationType
    transport_lane: str | None = None
    case_id: str
    entity_id: str
    entity_name: str
    participants: list[CollaborationParticipant]
    contributions: list[CollaborationContribution]
    final_summary: str

    @field_validator("session_id", "case_id", "entity_id", "entity_name", "final_summary")
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{info.field_name} must be non-empty")
        return cleaned
