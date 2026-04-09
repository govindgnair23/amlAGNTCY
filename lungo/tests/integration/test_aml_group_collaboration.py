from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aml314b.common.collaboration import validate_collaboration_session_request
from aml314b.common.enforcement import PlaceholderEnforcementLayer
from aml314b.common.probing import LaneProbeResponse
from aml314b.common.schemas import (
    CollaborationSessionRequest,
    CollaborationSessionResult,
    DiscoveryAggregateResult,
)
from aml314b.common.stores import (
    CuratedInvestigativeContextStore,
    KnownHighRiskEntitiesStore,
    LaneSubscriptionStore,
)
from aml314b.fi_a.graph.graph import AMLGroupCollaborationGraph
from aml314b.fi_a.graph.tools import (
    run_case_discovery_and_collaboration,
    run_discovery_and_collaboration,
)
from aml314b.fi_a.main import create_app
from aml314b.institutions.common.collaboration_agent import InstitutionCollaborationAgent
from aml314b.institutions.common.discovery_agent import InstitutionDiscoveryAgent

LUNGO_DIR = Path(__file__).resolve().parents[2]
AML_DIR = LUNGO_DIR / "aml314b"
PROMPT_CASES = json.loads(
    (Path(__file__).parent / "aml_group_collaboration_prompt_cases.json").read_text()
)["cases"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(params=PROMPT_CASES, ids=lambda case: str(case["investigation_type"]))
def prompt_case(request: pytest.FixtureRequest) -> dict[str, object]:
    return dict(request.param)


def _load_supported_investigation_types(institution_slug: str):
    return tuple(
        LaneSubscriptionStore(
            AML_DIR / "institutions" / institution_slug / "data" / "lane_subscriptions.csv"
        ).list_supported_investigation_types()
    )


def _build_agents():
    institutions: dict[str, dict[str, object]] = {}
    for institution_slug in ("fi_b", "fi_c", "fi_d", "fi_e", "fi_f"):
        institution_id = institution_slug.upper()
        enforcement = PlaceholderEnforcementLayer(
            logger_name=f"test.aml314b.{institution_slug}.enforcement"
        )
        institutions[institution_id] = {
            "discovery": InstitutionDiscoveryAgent(
                institution_id=institution_id,
                known_high_risk_store=KnownHighRiskEntitiesStore(
                    AML_DIR
                    / "institutions"
                    / institution_slug
                    / "data"
                    / "known_high_risk_entities.csv"
                ),
                enforcement=enforcement,
                supported_investigation_types=_load_supported_investigation_types(
                    institution_slug
                ),
            ),
            "collaboration": InstitutionCollaborationAgent(
                institution_id=institution_id,
                investigative_context_store=CuratedInvestigativeContextStore(
                    AML_DIR
                    / "institutions"
                    / institution_slug
                    / "data"
                    / "curated_investigative_context.csv"
                ),
                enforcement=enforcement,
                supported_investigation_types=_load_supported_investigation_types(
                    institution_slug
                ),
            ),
        }
    return institutions


def _build_probe_collector():
    supported_by_institution = {
        institution_slug.upper(): _load_supported_investigation_types(institution_slug)
        for institution_slug in ("fi_b", "fi_c", "fi_d", "fi_e", "fi_f")
    }

    async def collector(request):
        responses = []
        for institution_id, supported_investigation_types in supported_by_institution.items():
            if request.investigation_type in supported_investigation_types:
                responses.append(
                    LaneProbeResponse(
                        probe_id=request.probe_id,
                        responder_institution_id=institution_id,
                        investigation_type=request.investigation_type,
                    )
                )
        return responses

    return collector


def _build_collaboration_func():
    institutions = _build_agents()

    async def discovery_sender(request, route):
        return await institutions[route.institution_id]["discovery"].evaluate_request(request)

    async def collaboration_sender(request, route):
        return await institutions[route.institution_id]["collaboration"].contribute(request)

    async def wrapped(
        investigation_type: str,
        case_id: str,
        entity_id: str,
        entity_name: str,
        case_context: str,
    ):
        return await run_discovery_and_collaboration(
            investigation_type,
            case_id,
            entity_id,
            entity_name,
            case_context,
            discovery_sender=discovery_sender,
            collaboration_sender=collaboration_sender,
            probe_collector=_build_probe_collector(),
            directory_path=str(AML_DIR / "data" / "counterparty_directory.csv"),
            active_investigations_path=str(AML_DIR / "fi_a" / "data" / "active_investigations.csv"),
            transport_name="A2A",
        )

    return wrapped


def _build_structured_collaboration_runner():
    institutions = _build_agents()

    async def discovery_sender(request, route):
        return await institutions[route.institution_id]["discovery"].evaluate_request(request)

    async def collaboration_sender(request, route):
        return await institutions[route.institution_id]["collaboration"].contribute(request)

    async def wrapped(
        investigation_type: str,
        case_id: str,
        candidate_institutions: list[str] | None,
    ):
        return await run_case_discovery_and_collaboration(
            investigation_type,
            case_id,
            discovery_sender=discovery_sender,
            collaboration_sender=collaboration_sender,
            candidate_institutions=candidate_institutions,
            directory_path=str(AML_DIR / "data" / "counterparty_directory.csv"),
            active_investigations_path=str(AML_DIR / "fi_a" / "data" / "active_investigations.csv"),
            transport_name="A2A",
        )

    return wrapped


def test_collaboration_session_validation_rejects_declined_institution() -> None:
    request = CollaborationSessionRequest(
        session_id="collaboration-test",
        investigation_type="MONEY_MULE",
        case_id="CASE-JOHN-01",
        entity_id="ENTITY-JOHN-01",
        entity_name="John Doe",
        originating_institution_id="FI_A",
        participant_institution_ids=["FI_A", "FI_B", "FI_C", "FI_D", "FI_E"],
        case_context="cash deposited at FI_A and transferred outward",
        accepted_institutions=["FI_B", "FI_C", "FI_D"],
    )

    with pytest.raises(
        ValueError,
        match="Collaboration participants must be exactly the originating institution",
    ):
        validate_collaboration_session_request(request)


@pytest.mark.parametrize(
    ("entity_id", "expected_accepting_institutions", "expected_excluded_with_context"),
    [
        ("ENTITY-JOHN-01", ["FI_B", "FI_C", "FI_D"], ["FI_E", "FI_F"]),
        ("ENTITY-SAFIYA-01", ["FI_C", "FI_E", "FI_F"], ["FI_B", "FI_D"]),
    ],
)
def test_collaboration_fixture_loading_shows_acceptors_and_excluded_data(
    entity_id: str,
    expected_accepting_institutions: list[str],
    expected_excluded_with_context: list[str],
) -> None:
    accepting_institutions = []
    excluded_with_context = []
    for institution_slug in ("fi_b", "fi_c", "fi_d", "fi_e", "fi_f"):
        institution_id = institution_slug.upper()
        risk_store = KnownHighRiskEntitiesStore(
            AML_DIR / "institutions" / institution_slug / "data" / "known_high_risk_entities.csv"
        )
        context_store = CuratedInvestigativeContextStore(
            AML_DIR / "institutions" / institution_slug / "data" / "curated_investigative_context.csv"
        )
        if risk_store.has_entity(entity_id):
            accepting_institutions.append(institution_id)
        elif context_store.get_context(entity_id) is not None:
            excluded_with_context.append(institution_id)

    assert accepting_institutions == expected_accepting_institutions
    assert excluded_with_context == expected_excluded_with_context


@pytest.mark.anyio
async def test_declining_institution_rejects_collaboration_without_acceptance() -> None:
    agent = InstitutionCollaborationAgent(
        institution_id="FI_E",
        investigative_context_store=CuratedInvestigativeContextStore(
            AML_DIR / "institutions" / "fi_e" / "data" / "curated_investigative_context.csv"
        ),
        enforcement=PlaceholderEnforcementLayer(),
    )
    request = CollaborationSessionRequest(
        session_id="collaboration-test",
        investigation_type="MONEY_MULE",
        case_id="CASE-JOHN-01",
        entity_id="ENTITY-JOHN-01",
        entity_name="John Doe",
        originating_institution_id="FI_A",
        participant_institution_ids=["FI_A", "FI_B", "FI_C", "FI_D"],
        case_context="cash deposited at FI_A and transferred outward",
        accepted_institutions=["FI_B", "FI_C", "FI_D"],
    )

    with pytest.raises(ValueError, match="FI_E is not part of collaboration session"):
        await agent.contribute(request)


def test_group_collaboration_endpoint_filters_participants_and_emits_steps(
    prompt_case: dict[str, object]
) -> None:
    collaboration_graph = AMLGroupCollaborationGraph(
        collaboration_func=_build_collaboration_func()
    )
    app = create_app(collaboration_graph=collaboration_graph)
    client = TestClient(app)

    response = client.post(
        "/agent/prompt/collaboration",
        json={
            "prompt": prompt_case["prompt"],
            "investigation_type": prompt_case["investigation_type"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    discovery_result = DiscoveryAggregateResult.model_validate(payload["discovery_result"])
    collaboration_result = CollaborationSessionResult.model_validate(
        payload["collaboration_result"]
    )

    assert discovery_result.discovery_session_id.startswith("discovery-")
    assert collaboration_result.session_id.startswith("collaboration-")
    assert discovery_result.discovery_session_id != collaboration_result.session_id
    assert discovery_result.investigation_type == prompt_case["investigation_type"]
    assert discovery_result.transport_lane is None
    assert discovery_result.candidate_institutions == prompt_case["expected_candidates"]
    assert discovery_result.candidate_response_count == len(prompt_case["expected_candidates"])
    assert discovery_result.candidate_resolution_source == "NATS_LANE_PROBE"
    assert collaboration_result.investigation_type == prompt_case["investigation_type"]
    assert collaboration_result.transport_lane is None
    assert payload["observability"]["session_id"]
    assert "traceparent_id" in payload["observability"]
    assert discovery_result.accepted_institutions == prompt_case["expected_accepted"]
    assert discovery_result.declined_institutions == prompt_case["expected_declined"]
    assert [
        participant["institution_id"]
        for participant in payload["collaboration_result"]["participants"]
    ] == prompt_case["expected_participants"]
    assert [
        item["institution_id"]
        for item in payload["collaboration_result"]["contributions"]
    ] == prompt_case["expected_contributors"]
    assert len(payload["collaboration_result"]["contributions"]) == len(
        prompt_case["expected_contributors"]
    )

    if prompt_case["investigation_type"] == "MONEY_MULE":
        assert payload["response"] == (
            f"Collaboration completed for case CASE-JOHN-01 in session {collaboration_result.session_id}. "
            "Participants: FI_A, FI_B, FI_C, FI_D. "
            "Summary: FI_A shared case context: cash deposited at FI_A and transferred to external institutions over a two week period. "
            "FI_B contributed: FI_B observed recurring cash deposits tied to John Doe before funds moved outward. "
            "FI_C contributed: FI_C identified transaction review history linking John Doe to rapid movement of funds. "
            "FI_D contributed: FI_D identified adverse media correlation notes tied to John Doe and related counterparties.."
        )
    else:
        assert payload["response"] == (
            f"Collaboration completed for case CASE-SAFIYA-01 in session {collaboration_result.session_id}. "
            "Participants: FI_A, FI_C, FI_F. "
            "Summary: FI_A shared case context: inbound transfers from multiple remitters were followed by rapid cross-border movement linked to a suspected facilitation network. "
            "FI_C contributed: FI_C linked Safiya Rahman to rapid beneficiary turnover following inbound remittance activity. "
            "FI_F contributed: FI_F observed recurring inbound remittances to Safiya Rahman followed by rapid international forwarding activity.."
        )

    step_names = [event["step_name"] for event in payload["step_events"]]
    expected_step_names = [
        "lane_probe_sent",
        "lane_probe_response_received",
        "lane_probe_response_received",
        "lane_probe_response_received",
        "lane_probe_response_received",
        "candidate_set_finalized",
        "discovery_request_created",
        "discovery_broadcast_sent",
        "institution_response_received",
        "institution_response_received",
        "institution_response_received",
        "institution_response_received",
        "discovery_result_set_finalized",
        "discovery_completed",
        "collaboration_session_created",
        "collaboration_participants_selected",
    ]
    expected_step_names.extend(
        ["collaboration_contribution_received"] * len(prompt_case["expected_contributors"])
    )
    expected_step_names.append("collaboration_completed")
    assert step_names == expected_step_names
    assert [event["investigation_type"] for event in payload["step_events"]] == [
        prompt_case["investigation_type"]
    ] * len(payload["step_events"])

    step_events_response = client.get(
        "/agent/step-events",
        params={
            "case_id": discovery_result.case_id,
            "since_id": payload["step_events"][0]["id"] - 1,
            "investigation_type": prompt_case["investigation_type"],
        },
    )
    assert step_events_response.status_code == 200
    assert step_events_response.json()["events"] == payload["step_events"]


def test_structured_case_run_collaboration_uses_only_explicit_acceptors() -> None:
    app = create_app(
        structured_collaboration_runner=_build_structured_collaboration_runner(),
        active_investigations_path=str(AML_DIR / "fi_a" / "data" / "active_investigations.csv"),
    )
    client = TestClient(app)

    response = client.post(
        "/agent/cases/run",
        json={
            "case_id": "CASE-SAFIYA-01",
            "investigation_type": "TERRORIST_FINANCING",
            "run_mode": "collaboration",
            "candidate_institutions": ["FI_B", "FI_C", "FI_D", "FI_F"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    discovery_result = DiscoveryAggregateResult.model_validate(payload["discovery_result"])
    collaboration_result = CollaborationSessionResult.model_validate(
        payload["collaboration_result"]
    )

    assert discovery_result.candidate_institutions == ["FI_B", "FI_C", "FI_D", "FI_F"]
    assert discovery_result.accepted_institutions == ["FI_C", "FI_F"]
    assert discovery_result.declined_institutions == ["FI_B", "FI_D"]
    assert [participant.institution_id for participant in collaboration_result.participants] == [
        "FI_A",
        "FI_C",
        "FI_F",
    ]
    assert [
        contribution.institution_id for contribution in collaboration_result.contributions
    ] == ["FI_C", "FI_F"]
    assert payload["step_events"][0]["step_name"] == "discovery_request_created"
