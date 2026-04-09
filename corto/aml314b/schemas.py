from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


RequestPurpose = Literal["AML_314B"]
RequestedArtifact = Literal["MATCH_ONLY", "BOUNDED_CONTEXT"]
MatchType = Literal["NO_MATCH", "POTENTIAL_MATCH", "CONFIRMED_MATCH"]
RetentionPolicy = Literal["case_lifetime"]


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
        # Hard bound for Phase 1.a placeholder policy enforcement.
        return bounded[:500]
