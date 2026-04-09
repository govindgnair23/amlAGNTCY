from __future__ import annotations

from uuid import uuid4

from aml314b.common.schemas import (
    CollaborationParticipant,
    CollaborationSessionRequest,
    CollaborationSessionResult,
    DiscoveryAggregateResult,
)

DEFAULT_ORIGINATING_INSTITUTION_ID = "FI_A"
DISCOVERY_SESSION_PREFIX = "discovery"
COLLABORATION_SESSION_PREFIX = "collaboration"


def create_discovery_session_id() -> str:
    return f"{DISCOVERY_SESSION_PREFIX}-{uuid4()}"


def create_collaboration_session_id() -> str:
    return f"{COLLABORATION_SESSION_PREFIX}-{uuid4()}"


def build_collaboration_session_request(
    *,
    discovery_result: DiscoveryAggregateResult,
    case_context: str,
    session_id: str | None = None,
    originating_institution_id: str = DEFAULT_ORIGINATING_INSTITUTION_ID,
) -> CollaborationSessionRequest:
    participant_institution_ids = [
        originating_institution_id,
        *sorted(discovery_result.accepted_institutions),
    ]
    request = CollaborationSessionRequest(
        session_id=session_id or create_collaboration_session_id(),
        investigation_type=discovery_result.investigation_type,
        transport_lane=discovery_result.transport_lane,
        case_id=discovery_result.case_id,
        entity_id=discovery_result.entity_id,
        entity_name=discovery_result.entity_name,
        originating_institution_id=originating_institution_id,
        participant_institution_ids=participant_institution_ids,
        case_context=case_context,
        accepted_institutions=sorted(discovery_result.accepted_institutions),
    )
    validate_collaboration_session_request(request)
    return request


def validate_collaboration_session_request(request: CollaborationSessionRequest) -> None:
    originator = request.originating_institution_id.strip().upper()
    participants = [institution_id.strip().upper() for institution_id in request.participant_institution_ids]
    accepted = [institution_id.strip().upper() for institution_id in request.accepted_institutions]
    expected_participants = [originator, *accepted]

    if originator not in participants:
        raise ValueError("Collaboration session must include the originating institution.")
    if participants != expected_participants:
        raise ValueError(
            "Collaboration participants must be exactly the originating institution "
            "followed by the accepted institutions."
        )
    if originator in accepted:
        raise ValueError("Accepted institutions must not include the originating institution.")
    if len(set(participants)) != len(participants):
        raise ValueError("Collaboration participants must be unique.")
    if len(set(accepted)) != len(accepted):
        raise ValueError("Accepted institutions must be unique.")


def derive_collaboration_participants(
    request: CollaborationSessionRequest,
) -> list[CollaborationParticipant]:
    participants: list[CollaborationParticipant] = []
    for institution_id in request.participant_institution_ids:
        role = "ORIGINATOR" if institution_id == request.originating_institution_id else "RESPONDER"
        participants.append(
            CollaborationParticipant(
                institution_id=institution_id,
                display_name=institution_id,
                role=role,
            )
        )
    return participants


def build_deterministic_collaboration_summary(
    *, case_context: str, result: CollaborationSessionResult
) -> str:
    ordered_contributions = sorted(result.contributions, key=lambda item: item.sequence_number)
    contribution_segments = [
        f"{contribution.institution_id} contributed: {contribution.contribution}"
        for contribution in ordered_contributions
    ]
    summary_segments = [f"FI_A shared case context: {case_context}", *contribution_segments]
    return " ".join(summary_segments)
