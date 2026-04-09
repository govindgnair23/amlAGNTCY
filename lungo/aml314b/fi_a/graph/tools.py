from __future__ import annotations

from collections.abc import Awaitable, Callable

from aml314b.common.channeling import (
    InvestigationType,
    describe_investigation_lane,
)
from aml314b.common.collaboration import (
    build_collaboration_session_request,
    build_deterministic_collaboration_summary,
    create_discovery_session_id,
    derive_collaboration_participants,
)
from aml314b.common.enforcement import PlaceholderEnforcementLayer
from aml314b.common.probing import (
    CandidateResolutionSource,
    LaneProbeNatsClient,
    LaneProbeRequest,
    LaneProbeResult,
    LaneProbeResponse,
    normalize_candidate_institutions,
)
from aml314b.common.schemas import (
    CollaborationContribution,
    CollaborationSessionRequest,
    CollaborationSessionResult,
    DiscoveryAggregateResult,
    DiscoveryRequest,
    DiscoveryResponse,
)
from aml314b.common.step_events import StepEventBuffer
from aml314b.common.stores import (
    ActiveCase,
    ActiveInvestigationsStore,
    CounterpartyDirectoryStore,
    DirectoryRoute,
)
from aml314b.fi_a.a2a_client import CollaborationA2AClient, DiscoveryA2AClient
from config.config import (
    AML314B_ACTIVE_INVESTIGATIONS_PATH,
    AML314B_DEFAULT_REQUESTER_INSTITUTION_ID,
    AML314B_DIRECTORY_PATH,
    AML314B_MESSAGE_TRANSPORT,
    AML314B_PROBE_NATS_ENDPOINT,
    AML314B_PROBE_RESPONSE_TIMEOUT_MS,
    AML314B_PROBE_TRANSPORT,
)

DiscoverySender = Callable[[DiscoveryRequest, DirectoryRoute], Awaitable[DiscoveryResponse]]
CollaborationSender = Callable[
    [CollaborationSessionRequest, DirectoryRoute],
    Awaitable[CollaborationContribution],
]
ProbeCollector = Callable[[LaneProbeRequest], Awaitable[list[LaneProbeResponse]]]
STEP_BUFFER = StepEventBuffer()


async def _default_sender(request: DiscoveryRequest, route: DirectoryRoute) -> DiscoveryResponse:
    client = DiscoveryA2AClient(transport_name=AML314B_MESSAGE_TRANSPORT)
    return await client.send_request(request, route)


async def _default_collaboration_sender(
    request: CollaborationSessionRequest, route: DirectoryRoute
) -> CollaborationContribution:
    client = CollaborationA2AClient(transport_name=AML314B_MESSAGE_TRANSPORT)
    return await client.send_request(request, route)


async def _default_probe_collector(request: LaneProbeRequest) -> list[LaneProbeResponse]:
    if AML314B_PROBE_TRANSPORT != "NATS":
        raise ValueError(
            "AML314B_PROBE_TRANSPORT must be NATS for the default lane probe collector."
        )
    client = LaneProbeNatsClient(
        endpoint=AML314B_PROBE_NATS_ENDPOINT,
        response_timeout_ms=AML314B_PROBE_RESPONSE_TIMEOUT_MS,
    )
    return await client.collect(request)


def _build_candidate_routes(
    *,
    candidate_institutions: list[str],
    directory_path: str,
    transport_name: str,
) -> list[DirectoryRoute]:
    directory_store = CounterpartyDirectoryStore(directory_path)
    return [
        directory_store.get_route(
            institution_id=institution_id,
            transport=transport_name,
        )
        for institution_id in candidate_institutions
    ]


async def probe_investigation_lane(
    investigation_type: str | InvestigationType,
    *,
    directory_path: str = AML314B_DIRECTORY_PATH,
    transport_name: str = AML314B_MESSAGE_TRANSPORT,
    requestor_institution_id: str = AML314B_DEFAULT_REQUESTER_INSTITUTION_ID,
    probe_collector: ProbeCollector | None = None,
) -> LaneProbeResult:
    probe_collector = probe_collector or _default_probe_collector
    lane_descriptor = describe_investigation_lane(investigation_type)
    request = LaneProbeRequest(
        requestor_institution_id=requestor_institution_id,
        investigation_type=lane_descriptor.investigation_type,
    )
    raw_responses = await probe_collector(request)
    deduplicated_responses = sorted(
        {
            response.responder_institution_id: response
            for response in raw_responses
            if response.probe_id == request.probe_id
            and response.investigation_type == lane_descriptor.investigation_type
            and response.decision == "YES"
        }.values(),
        key=lambda response: response.responder_institution_id,
    )
    routes = _build_candidate_routes(
        candidate_institutions=[
            response.responder_institution_id for response in deduplicated_responses
        ],
        directory_path=directory_path,
        transport_name=transport_name,
    )
    return LaneProbeResult(
        probe_id=request.probe_id,
        investigation_type=lane_descriptor.investigation_type,
        candidate_institutions=[route.institution_id for route in routes],
        candidate_response_count=len(deduplicated_responses),
        responses=deduplicated_responses,
    )


async def discover_lane_candidates(
    investigation_type: str | InvestigationType,
    *,
    case_id: str,
    directory_path: str,
    transport_name: str,
    requestor_institution_id: str,
    probe_collector: ProbeCollector | None = None,
) -> tuple[list[DirectoryRoute], list[LaneProbeResponse], CandidateResolutionSource]:
    lane_descriptor = describe_investigation_lane(investigation_type)
    event_transport_lane = (
        lane_descriptor.transport_lane if transport_name.upper() == "SLIM" else None
    )
    probe_result = await probe_investigation_lane(
        lane_descriptor.investigation_type,
        directory_path=directory_path,
        transport_name=transport_name,
        requestor_institution_id=requestor_institution_id,
        probe_collector=probe_collector,
    )
    STEP_BUFFER.append_raw(
        case_id=case_id,
        investigation_type=lane_descriptor.investigation_type.value,
        transport_lane=event_transport_lane,
        step_name="lane_probe_sent",
        message=(
            f"FI_A published probe {probe_result.probe_id} on "
            f"aml314b.probe.{lane_descriptor.topic_suffix}."
        ),
    )
    for response in probe_result.responses:
        STEP_BUFFER.append_raw(
            case_id=case_id,
            investigation_type=lane_descriptor.investigation_type.value,
            transport_lane=event_transport_lane,
            step_name="lane_probe_response_received",
            message=(
                f"{response.responder_institution_id} replied YES to probe "
                f"{probe_result.probe_id}."
            ),
        )
    routes = _build_candidate_routes(
        candidate_institutions=probe_result.candidate_institutions,
        directory_path=directory_path,
        transport_name=transport_name,
    )
    STEP_BUFFER.append_raw(
        case_id=case_id,
        investigation_type=lane_descriptor.investigation_type.value,
        transport_lane=event_transport_lane,
        step_name="candidate_set_finalized",
        message=(
            "Lane probe candidates: "
            f"{', '.join(probe_result.candidate_institutions) or 'none'}."
        ),
    )
    return routes, probe_result.responses, probe_result.candidate_resolution_source


async def broadcast_discovery(
    investigation_type: str | InvestigationType,
    case_id: str,
    entity_id: str,
    entity_name: str,
    case_context: str,
    *,
    case: ActiveCase | None = None,
    sender: DiscoverySender | None = None,
    probe_collector: ProbeCollector | None = None,
    candidate_institutions: list[str] | None = None,
    directory_path: str = AML314B_DIRECTORY_PATH,
    active_investigations_path: str = AML314B_ACTIVE_INVESTIGATIONS_PATH,
    transport_name: str = AML314B_MESSAGE_TRANSPORT,
    requestor_institution_id: str = AML314B_DEFAULT_REQUESTER_INSTITUTION_ID,
) -> DiscoveryAggregateResult:
    sender = sender or _default_sender
    lane_descriptor = describe_investigation_lane(investigation_type)
    transport_lane = lane_descriptor.transport_lane if transport_name.upper() == "SLIM" else None
    case = case or ActiveInvestigationsStore(active_investigations_path).get_case(
        case_id,
        lane_descriptor.investigation_type,
    )
    discovery_session_id = create_discovery_session_id()
    if candidate_institutions is None:
        routes, probe_responses, candidate_resolution_source = await discover_lane_candidates(
            lane_descriptor.investigation_type,
            case_id=case_id,
            directory_path=directory_path,
            transport_name=transport_name,
            requestor_institution_id=requestor_institution_id,
            probe_collector=probe_collector,
        )
        resolved_candidate_institutions = [route.institution_id for route in routes]
    else:
        resolved_candidate_institutions = normalize_candidate_institutions(
            candidate_institutions
        )
        routes = _build_candidate_routes(
            candidate_institutions=resolved_candidate_institutions,
            directory_path=directory_path,
            transport_name=transport_name,
        )
        probe_responses = [
            LaneProbeResponse(
                probe_id="STRUCTURED_SELECTION",
                responder_institution_id=route.institution_id,
                investigation_type=lane_descriptor.investigation_type,
            )
            for route in routes
        ]
        candidate_resolution_source = "NATS_LANE_PROBE"

    enforcement = PlaceholderEnforcementLayer(logger_name="lungo.aml314b.fi_a.enforcement")
    STEP_BUFFER.append_raw(
        case_id=case_id,
        investigation_type=lane_descriptor.investigation_type.value,
        transport_lane=transport_lane,
        step_name="discovery_request_created",
        message=(
            f"FI_A created a {lane_descriptor.lane_label} discovery request for "
            f"{entity_id} in session {discovery_session_id}."
        ),
    )
    requests = []
    for route in routes:
        request = DiscoveryRequest(
            requestor_institution_id=requestor_institution_id,
            target_institution_id=route.institution_id,
            investigation_type=lane_descriptor.investigation_type,
            transport_lane=transport_lane,
            case_id=case.case_id,
            entity_id=entity_id,
            entity_name=entity_name,
            case_context=case_context,
            time_window=case.to_time_window(),
        )
        requests.append((route, enforcement.enforce_outbound_discovery_request(request)))

    STEP_BUFFER.append_raw(
        case_id=case_id,
        investigation_type=lane_descriptor.investigation_type.value,
        transport_lane=transport_lane,
        step_name="discovery_broadcast_sent",
        message=(
            f"FI_A broadcast the {lane_descriptor.lane_label} discovery request to "
            f"{len(requests)} institutions."
        ),
    )

    responses: list[DiscoveryResponse] = []
    for route, request in requests:
        response = await sender(request, route)
        enforced_response = enforcement.enforce_inbound_discovery_response(
            response,
            case_id=request.case_id,
        )
        if enforced_response.investigation_type != request.investigation_type:
            raise ValueError(
                "Discovery response investigation_type did not match the outbound request."
            )
        if enforced_response.transport_lane != request.transport_lane:
            raise ValueError("Discovery response transport_lane did not match the outbound request.")
        STEP_BUFFER.append_raw(
            case_id=case_id,
            investigation_type=lane_descriptor.investigation_type.value,
            transport_lane=transport_lane,
            step_name="institution_response_received",
            message=(
                f"{enforced_response.responder_institution_id} responded "
                f"{enforced_response.decision} for the {lane_descriptor.lane_label} lane."
            ),
        )
        responses.append(enforced_response)

    accepted_institutions = sorted(
        response.responder_institution_id
        for response in responses
        if response.decision == "ACCEPT"
    )
    declined_institutions = sorted(
        response.responder_institution_id
        for response in responses
        if response.decision == "DECLINE"
    )
    STEP_BUFFER.append_raw(
        case_id=case_id,
        investigation_type=lane_descriptor.investigation_type.value,
        transport_lane=transport_lane,
        step_name="discovery_result_set_finalized",
        message=(
            f"Accepted: {', '.join(accepted_institutions) or 'none'}. "
            f"Declined: {', '.join(declined_institutions) or 'none'}."
        ),
    )
    STEP_BUFFER.append_raw(
        case_id=case_id,
        investigation_type=lane_descriptor.investigation_type.value,
        transport_lane=transport_lane,
        step_name="discovery_completed",
        message=(
            f"Discovery session {discovery_session_id} completed for the "
            f"{lane_descriptor.lane_label} lane."
        ),
    )
    return DiscoveryAggregateResult(
        discovery_session_id=discovery_session_id,
        investigation_type=lane_descriptor.investigation_type,
        transport_lane=transport_lane,
        case_id=case_id,
        entity_id=entity_id,
        entity_name=entity_name,
        candidate_institutions=resolved_candidate_institutions,
        candidate_response_count=len(probe_responses),
        candidate_resolution_source=candidate_resolution_source,
        accepted_institutions=accepted_institutions,
        declined_institutions=declined_institutions,
        response_count=len(responses),
        responses=responses,
    )


async def run_collaboration_from_discovery(
    discovery_result: DiscoveryAggregateResult,
    case_context: str,
    *,
    sender: CollaborationSender | None = None,
    directory_path: str = AML314B_DIRECTORY_PATH,
    transport_name: str = AML314B_MESSAGE_TRANSPORT,
    requestor_institution_id: str = AML314B_DEFAULT_REQUESTER_INSTITUTION_ID,
) -> CollaborationSessionResult:
    sender = sender or _default_collaboration_sender
    directory_store = CounterpartyDirectoryStore(directory_path)
    enforcement = PlaceholderEnforcementLayer(logger_name="lungo.aml314b.fi_a.enforcement")
    session_request = build_collaboration_session_request(
        discovery_result=discovery_result,
        case_context=case_context,
        originating_institution_id=requestor_institution_id,
    )
    lane_descriptor = describe_investigation_lane(discovery_result.investigation_type)
    STEP_BUFFER.append_raw(
        case_id=discovery_result.case_id,
        investigation_type=discovery_result.investigation_type.value,
        transport_lane=discovery_result.transport_lane,
        step_name="collaboration_session_created",
        message=(
            f"FI_A created a {lane_descriptor.lane_label} collaboration session "
            f"{session_request.session_id}."
        ),
    )
    STEP_BUFFER.append_raw(
        case_id=discovery_result.case_id,
        investigation_type=discovery_result.investigation_type.value,
        transport_lane=discovery_result.transport_lane,
        step_name="collaboration_participants_selected",
        message=(
            "Collaboration participants: "
            f"{', '.join(session_request.participant_institution_ids)}."
        ),
    )

    contributions: list[CollaborationContribution] = []
    for institution_id in session_request.accepted_institutions:
        route = directory_store.get_route(institution_id=institution_id, transport=transport_name)
        enforced_request = enforcement.enforce_outbound_collaboration_request(session_request)
        contribution = await sender(enforced_request, route)
        enforced_contribution = enforcement.enforce_inbound_collaboration_contribution(
            contribution,
            case_id=discovery_result.case_id,
        )
        if enforced_contribution.investigation_type != session_request.investigation_type:
            raise ValueError(
                "Collaboration contribution investigation_type did not match the session request."
            )
        if enforced_contribution.transport_lane != session_request.transport_lane:
            raise ValueError(
                "Collaboration contribution transport_lane did not match the session request."
            )
        STEP_BUFFER.append_raw(
            case_id=discovery_result.case_id,
            investigation_type=discovery_result.investigation_type.value,
            transport_lane=discovery_result.transport_lane,
            step_name="collaboration_contribution_received",
            message=(
                f"{enforced_contribution.institution_id} contributed in session "
                f"{session_request.session_id}."
            ),
        )
        contributions.append(enforced_contribution)

    participants = derive_collaboration_participants(session_request)
    result = CollaborationSessionResult(
        session_id=session_request.session_id,
        investigation_type=discovery_result.investigation_type,
        transport_lane=discovery_result.transport_lane,
        case_id=discovery_result.case_id,
        entity_id=discovery_result.entity_id,
        entity_name=discovery_result.entity_name,
        participants=participants,
        contributions=contributions,
        final_summary="pending",
    )
    final_summary = build_deterministic_collaboration_summary(
        case_context=case_context,
        result=result,
    )
    result = result.model_copy(update={"final_summary": final_summary})
    STEP_BUFFER.append_raw(
        case_id=discovery_result.case_id,
        investigation_type=discovery_result.investigation_type.value,
        transport_lane=discovery_result.transport_lane,
        step_name="collaboration_completed",
        message=(
            f"Collaboration session {session_request.session_id} completed for the "
            f"{lane_descriptor.lane_label} lane."
        ),
    )
    return result


def _load_structured_case(
    *,
    case_id: str,
    investigation_type: str | InvestigationType,
    active_investigations_path: str,
):
    return ActiveInvestigationsStore(active_investigations_path).get_case(
        case_id,
        describe_investigation_lane(investigation_type).investigation_type,
    )


def _require_case_activity_summary(case) -> str:
    if not case.activity_summary:
        raise ValueError(
            "Selected case is missing case_summary and cannot drive structured discovery."
        )
    return case.activity_summary


async def run_case_discovery(
    investigation_type: str | InvestigationType,
    case_id: str,
    *,
    sender: DiscoverySender | None = None,
    probe_collector: ProbeCollector | None = None,
    candidate_institutions: list[str] | None = None,
    directory_path: str = AML314B_DIRECTORY_PATH,
    active_investigations_path: str = AML314B_ACTIVE_INVESTIGATIONS_PATH,
    transport_name: str = AML314B_MESSAGE_TRANSPORT,
    requestor_institution_id: str = AML314B_DEFAULT_REQUESTER_INSTITUTION_ID,
) -> DiscoveryAggregateResult:
    case = _load_structured_case(
        case_id=case_id,
        investigation_type=investigation_type,
        active_investigations_path=active_investigations_path,
    )
    case_activity_summary = _require_case_activity_summary(case)
    return await broadcast_discovery(
        investigation_type,
        case.case_id,
        case.entity_id,
        case.entity_name,
        case_activity_summary,
        case=case,
        sender=sender,
        probe_collector=probe_collector,
        candidate_institutions=candidate_institutions,
        directory_path=directory_path,
        active_investigations_path=active_investigations_path,
        transport_name=transport_name,
        requestor_institution_id=requestor_institution_id,
    )


async def run_case_discovery_and_collaboration(
    investigation_type: str | InvestigationType,
    case_id: str,
    *,
    discovery_sender: DiscoverySender | None = None,
    collaboration_sender: CollaborationSender | None = None,
    probe_collector: ProbeCollector | None = None,
    candidate_institutions: list[str] | None = None,
    directory_path: str = AML314B_DIRECTORY_PATH,
    active_investigations_path: str = AML314B_ACTIVE_INVESTIGATIONS_PATH,
    transport_name: str = AML314B_MESSAGE_TRANSPORT,
    requestor_institution_id: str = AML314B_DEFAULT_REQUESTER_INSTITUTION_ID,
) -> tuple[DiscoveryAggregateResult, CollaborationSessionResult]:
    case = _load_structured_case(
        case_id=case_id,
        investigation_type=investigation_type,
        active_investigations_path=active_investigations_path,
    )
    case_activity_summary = _require_case_activity_summary(case)
    discovery_result = await broadcast_discovery(
        investigation_type,
        case.case_id,
        case.entity_id,
        case.entity_name,
        case_activity_summary,
        case=case,
        sender=discovery_sender,
        probe_collector=probe_collector,
        candidate_institutions=candidate_institutions,
        directory_path=directory_path,
        active_investigations_path=active_investigations_path,
        transport_name=transport_name,
        requestor_institution_id=requestor_institution_id,
    )
    collaboration_result = await run_collaboration_from_discovery(
        discovery_result,
        case_activity_summary,
        sender=collaboration_sender,
        directory_path=directory_path,
        transport_name=transport_name,
        requestor_institution_id=requestor_institution_id,
    )
    return discovery_result, collaboration_result


async def run_discovery_and_collaboration(
    investigation_type: str | InvestigationType,
    case_id: str,
    entity_id: str,
    entity_name: str,
    case_context: str,
    *,
    discovery_sender: DiscoverySender | None = None,
    collaboration_sender: CollaborationSender | None = None,
    probe_collector: ProbeCollector | None = None,
    directory_path: str = AML314B_DIRECTORY_PATH,
    active_investigations_path: str = AML314B_ACTIVE_INVESTIGATIONS_PATH,
    transport_name: str = AML314B_MESSAGE_TRANSPORT,
    requestor_institution_id: str = AML314B_DEFAULT_REQUESTER_INSTITUTION_ID,
) -> tuple[DiscoveryAggregateResult, CollaborationSessionResult]:
    discovery_result = await broadcast_discovery(
        investigation_type,
        case_id,
        entity_id,
        entity_name,
        case_context,
        sender=discovery_sender,
        probe_collector=probe_collector,
        directory_path=directory_path,
        active_investigations_path=active_investigations_path,
        transport_name=transport_name,
        requestor_institution_id=requestor_institution_id,
    )
    collaboration_result = await run_collaboration_from_discovery(
        discovery_result,
        case_context,
        sender=collaboration_sender,
        directory_path=directory_path,
        transport_name=transport_name,
        requestor_institution_id=requestor_institution_id,
    )
    return discovery_result, collaboration_result


def format_discovery_summary(result: DiscoveryAggregateResult) -> str:
    accepted = ", ".join(result.accepted_institutions) if result.accepted_institutions else "none"
    declined = ", ".join(result.declined_institutions) if result.declined_institutions else "none"
    return (
        f"Discovery completed for case {result.case_id} and entity "
        f"{result.entity_name} ({result.entity_id}). "
        f"Accepted: {accepted}. Declined: {declined}."
    )


def format_collaboration_summary(result: CollaborationSessionResult) -> str:
    participants = ", ".join(participant.institution_id for participant in result.participants)
    return (
        f"Collaboration completed for case {result.case_id} in session {result.session_id}. "
        f"Participants: {participants}. Summary: {result.final_summary}."
    )

def get_step_events(
    *,
    case_id: str,
    since_id: int | None = None,
    investigation_type: str | None = None,
    transport_lane: str | None = None,
) -> list[dict[str, str | int | None]]:
    return STEP_BUFFER.get_since(
        case_id=case_id,
        since_id=since_id,
        investigation_type=investigation_type,
        transport_lane=transport_lane,
    )
