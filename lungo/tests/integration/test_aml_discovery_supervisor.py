from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from aml314b.common.enforcement import PlaceholderEnforcementLayer
from aml314b.common.probing import LaneProbeResponse
from aml314b.common.schemas import DiscoveryAggregateResult, DiscoveryRequest
from aml314b.common.stores import (
    ActiveInvestigationsStore,
    CounterpartyDirectoryStore,
    KnownHighRiskEntitiesStore,
    LaneSubscriptionStore,
)
from aml314b.fi_a.graph.graph import AMLDiscoveryGraph
from aml314b.fi_a.graph.tools import (
    broadcast_discovery,
    probe_investigation_lane,
    run_case_discovery,
)
from aml314b.fi_a.main import create_app
from aml314b.institutions.common.discovery_agent import InstitutionDiscoveryAgent
from aml314b.institutions.fi_b.card import AGENT_CARD as FI_B_CARD
from aml314b.institutions.fi_c.card import AGENT_CARD as FI_C_CARD
from aml314b.institutions.fi_d.card import AGENT_CARD as FI_D_CARD
from aml314b.institutions.fi_e.card import AGENT_CARD as FI_E_CARD
from aml314b.institutions.fi_f.card import AGENT_CARD as FI_F_CARD

LUNGO_DIR = Path(__file__).resolve().parents[2]
AML_DIR = LUNGO_DIR / "aml314b"
PROMPT_CASES = json.loads(
    (Path(__file__).parent / "aml_discovery_prompt_cases.json").read_text()
)["cases"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(params=PROMPT_CASES, ids=lambda case: str(case["id"]))
def prompt_case(request: pytest.FixtureRequest) -> dict[str, object]:
    return dict(request.param)


def _load_supported_investigation_types(institution_slug: str):
    return tuple(
        LaneSubscriptionStore(
            AML_DIR / "institutions" / institution_slug / "data" / "lane_subscriptions.csv"
        ).list_supported_investigation_types()
    )


def _build_responder_sender(*, capture_routes: list[str] | None = None):
    institutions = {}
    for institution_slug in ("fi_b", "fi_c", "fi_d", "fi_e", "fi_f"):
        institution_id = institution_slug.upper()
        store = KnownHighRiskEntitiesStore(
            AML_DIR / "institutions" / institution_slug / "data" / "known_high_risk_entities.csv"
        )
        institutions[institution_id] = InstitutionDiscoveryAgent(
            institution_id=institution_id,
            known_high_risk_store=store,
            enforcement=PlaceholderEnforcementLayer(
                logger_name=f"test.aml314b.{institution_slug}.enforcement"
            ),
            supported_investigation_types=_load_supported_investigation_types(institution_slug),
        )

    async def sender(request, route):
        if capture_routes is not None:
            capture_routes.append(route.endpoint)
        return await institutions[route.institution_id].evaluate_request(request)

    return sender


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


def _build_broadcast_func(
    *,
    directory_path: str | None = None,
    capture_routes: list[str] | None = None,
):
    sender = _build_responder_sender(capture_routes=capture_routes)

    async def wrapped(
        investigation_type: str,
        case_id: str,
        entity_id: str,
        entity_name: str,
        case_context: str,
    ):
        return await broadcast_discovery(
            investigation_type,
            case_id,
            entity_id,
            entity_name,
            case_context,
            sender=sender,
            probe_collector=_build_probe_collector(),
            directory_path=directory_path or str(AML_DIR / "data" / "counterparty_directory.csv"),
            active_investigations_path=str(AML_DIR / "fi_a" / "data" / "active_investigations.csv"),
            transport_name="A2A",
        )

    return wrapped


def _build_probe_runner():
    async def wrapped(investigation_type: str):
        return await probe_investigation_lane(
            investigation_type,
            probe_collector=_build_probe_collector(),
            directory_path=str(AML_DIR / "data" / "counterparty_directory.csv"),
            transport_name="A2A",
        )

    return wrapped


def _build_structured_discovery_runner(
    *,
    capture_routes: list[str] | None = None,
    capture_requests: list[DiscoveryRequest] | None = None,
):
    sender = _build_responder_sender(capture_routes=capture_routes)

    async def wrapped(
        investigation_type: str,
        case_id: str,
        candidate_institutions: list[str] | None,
    ):
        async def structured_sender(request: DiscoveryRequest, route):
            if capture_requests is not None:
                capture_requests.append(request)
            return await sender(request, route)

        return await run_case_discovery(
            investigation_type,
            case_id,
            sender=structured_sender,
            candidate_institutions=candidate_institutions,
            directory_path=str(AML_DIR / "data" / "counterparty_directory.csv"),
            active_investigations_path=str(AML_DIR / "fi_a" / "data" / "active_investigations.csv"),
            transport_name="A2A",
        )

    return wrapped


def test_shared_store_loading_succeeds() -> None:
    active_store = ActiveInvestigationsStore(AML_DIR / "fi_a" / "data" / "active_investigations.csv")
    directory_store = CounterpartyDirectoryStore(AML_DIR / "data" / "counterparty_directory.csv")

    money_mule_case = active_store.get_case("CASE-JOHN-01", "MONEY_MULE")
    terrorist_financing_case = active_store.get_case(
        "CASE-SAFIYA-01",
        "TERRORIST_FINANCING",
    )

    assert money_mule_case.entity_id == "ENTITY-JOHN-01"
    assert terrorist_financing_case.entity_id == "ENTITY-SAFIYA-01"
    assert len(directory_store.list_routes("A2A")) == 5


@pytest.mark.parametrize(
    ("entity_id", "expected_accepting_institutions"),
    [
        ("ENTITY-JOHN-01", ["FI_B", "FI_C", "FI_D"]),
        ("ENTITY-SAFIYA-01", ["FI_C", "FI_E", "FI_F"]),
    ],
)
def test_seeded_investigation_types_have_distinct_accepting_institutions(
    entity_id: str,
    expected_accepting_institutions: list[str],
) -> None:
    accepting_institutions = []
    for institution_slug in ("fi_b", "fi_c", "fi_d", "fi_e", "fi_f"):
        store = KnownHighRiskEntitiesStore(
            AML_DIR / "institutions" / institution_slug / "data" / "known_high_risk_entities.csv"
        )
        if store.has_entity(entity_id):
            accepting_institutions.append(institution_slug.upper())

    assert accepting_institutions == expected_accepting_institutions


def test_responder_agent_cards_publish_http_urls() -> None:
    cards = [FI_B_CARD, FI_C_CARD, FI_D_CARD, FI_E_CARD, FI_F_CARD]

    assert [card.url for card in cards] == [
        "http://127.0.0.1:9120",
        "http://127.0.0.1:9121",
        "http://127.0.0.1:9122",
        "http://127.0.0.1:9123",
        "http://127.0.0.1:9124",
    ]


@pytest.mark.anyio
async def test_single_responder_accepts_when_entity_present() -> None:
    store = KnownHighRiskEntitiesStore(
        AML_DIR / "institutions" / "fi_b" / "data" / "known_high_risk_entities.csv"
    )
    agent = InstitutionDiscoveryAgent(
        institution_id="FI_B",
        known_high_risk_store=store,
        enforcement=PlaceholderEnforcementLayer(),
    )
    request = DiscoveryRequest(
        requestor_institution_id="FI_A",
        target_institution_id="FI_B",
        investigation_type="MONEY_MULE",
        case_id="CASE-JOHN-01",
        entity_id="ENTITY-JOHN-01",
        entity_name="John Doe",
        case_context="cash deposited at FI_A and transferred outward",
        time_window=ActiveInvestigationsStore(
            AML_DIR / "fi_a" / "data" / "active_investigations.csv"
        ).get_case("CASE-JOHN-01", "MONEY_MULE").to_time_window(),
    )

    response = await agent.evaluate_request(request)

    assert response.investigation_type == "MONEY_MULE"
    assert response.transport_lane is None
    assert response.decision == "ACCEPT"
    assert response.reason == "Entity present in known high risk entities store."


@pytest.mark.anyio
async def test_single_responder_declines_when_entity_absent() -> None:
    store = KnownHighRiskEntitiesStore(
        AML_DIR / "institutions" / "fi_e" / "data" / "known_high_risk_entities.csv"
    )
    agent = InstitutionDiscoveryAgent(
        institution_id="FI_E",
        known_high_risk_store=store,
        enforcement=PlaceholderEnforcementLayer(),
    )
    request = DiscoveryRequest(
        requestor_institution_id="FI_A",
        target_institution_id="FI_E",
        investigation_type="MONEY_MULE",
        case_id="CASE-JOHN-01",
        entity_id="ENTITY-JOHN-01",
        entity_name="John Doe",
        case_context="cash deposited at FI_A and transferred outward",
        time_window=ActiveInvestigationsStore(
            AML_DIR / "fi_a" / "data" / "active_investigations.csv"
        ).get_case("CASE-JOHN-01", "MONEY_MULE").to_time_window(),
    )

    response = await agent.evaluate_request(request)

    assert response.investigation_type == "MONEY_MULE"
    assert response.transport_lane is None
    assert response.decision == "DECLINE"
    assert response.reason == "Entity not present in known high risk entities store."


def test_supervisor_aggregates_five_responses(prompt_case: dict[str, object]) -> None:
    graph = AMLDiscoveryGraph(broadcast_func=_build_broadcast_func())
    app = create_app(graph)
    client = TestClient(app)

    response = client.post(
        "/agent/prompt",
        json={
            "prompt": prompt_case["prompt"],
            "investigation_type": prompt_case["investigation_type"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    aggregate = DiscoveryAggregateResult.model_validate(payload["aggregate_result"])

    assert aggregate.investigation_type == prompt_case["investigation_type"]
    assert aggregate.transport_lane is None
    assert aggregate.candidate_institutions == prompt_case["expected_candidates"]


@pytest.mark.parametrize(
    ("investigation_type", "expected_candidates"),
    [
        ("MONEY_MULE", ["FI_B", "FI_C", "FI_D", "FI_E"]),
        ("TERRORIST_FINANCING", ["FI_B", "FI_C", "FI_D", "FI_F"]),
    ],
)
def test_probe_endpoint_returns_lane_shortlist(
    investigation_type: str,
    expected_candidates: list[str],
) -> None:
    app = create_app(lane_probe_runner=_build_probe_runner())
    client = TestClient(app)

    response = client.post("/agent/probe", json={"investigation_type": investigation_type})

    assert response.status_code == 200
    payload = response.json()["probe_result"]
    assert payload["investigation_type"] == investigation_type
    assert payload["candidate_institutions"] == expected_candidates
    assert payload["candidate_response_count"] == len(expected_candidates)
    assert [item["responder_institution_id"] for item in payload["responses"]] == expected_candidates


def test_cases_endpoint_filters_by_investigation_type() -> None:
    app = create_app(
        active_investigations_path=str(AML_DIR / "fi_a" / "data" / "active_investigations.csv")
    )
    client = TestClient(app)

    response = client.get(
        "/agent/cases",
        params={"investigation_type": "TERRORIST_FINANCING"},
    )

    assert response.status_code == 200
    payload = response.json()["cases"]
    assert [item["case_id"] for item in payload] == ["CASE-SAFIYA-01"]
    assert payload[0]["entity_id"] == "ENTITY-SAFIYA-01"
    assert payload[0]["case_summary"].startswith("inbound transfers from multiple remitters")


def test_structured_case_run_endpoint_builds_request_data_from_case_id() -> None:
    captured_routes: list[str] = []
    captured_requests: list[DiscoveryRequest] = []
    app = create_app(
        structured_discovery_runner=_build_structured_discovery_runner(
            capture_routes=captured_routes,
            capture_requests=captured_requests,
        ),
        active_investigations_path=str(AML_DIR / "fi_a" / "data" / "active_investigations.csv"),
    )
    client = TestClient(app)

    response = client.post(
        "/agent/cases/run",
        json={
            "case_id": "CASE-JOHN-01",
            "investigation_type": "MONEY_MULE",
            "run_mode": "discovery",
            "candidate_institutions": ["FI_B", "FI_C", "FI_D", "FI_E"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    aggregate = DiscoveryAggregateResult.model_validate(payload["aggregate_result"])

    assert aggregate.case_id == "CASE-JOHN-01"
    assert aggregate.entity_id == "ENTITY-JOHN-01"
    assert aggregate.entity_name == "John Doe"
    assert aggregate.candidate_institutions == ["FI_B", "FI_C", "FI_D", "FI_E"]
    assert aggregate.accepted_institutions == ["FI_B", "FI_C", "FI_D"]
    assert aggregate.declined_institutions == ["FI_E"]
    assert [request.target_institution_id for request in captured_requests] == [
        "FI_B",
        "FI_C",
        "FI_D",
        "FI_E",
    ]
    assert all(request.case_id == "CASE-JOHN-01" for request in captured_requests)
    assert all(request.entity_id == "ENTITY-JOHN-01" for request in captured_requests)
    assert all(request.entity_name == "John Doe" for request in captured_requests)
    assert captured_routes == [
        "http://127.0.0.1:9120",
        "http://127.0.0.1:9121",
        "http://127.0.0.1:9122",
        "http://127.0.0.1:9123",
    ]
    assert aggregate.candidate_response_count == 4
    assert aggregate.candidate_resolution_source == "NATS_LANE_PROBE"
    assert aggregate.response_count == 4
    assert payload["observability"]["session_id"]
    assert "traceparent_id" in payload["observability"]
    assert [event["investigation_type"] for event in payload["step_events"]] == [
        "MONEY_MULE"
    ] * len(payload["step_events"])
    assert {event["transport_lane"] for event in payload["step_events"]} == {None}
    assert payload["step_events"][0]["step_name"] == "discovery_request_created"
    assert [event["step_name"] for event in payload["step_events"][:3]] == [
        "discovery_request_created",
        "discovery_broadcast_sent",
        "institution_response_received",
    ]


def test_suggested_prompts_return_prompt_objects() -> None:
    app = create_app()
    client = TestClient(app)

    response = client.get("/suggested-prompts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["aml_discovery"] == [
        {
            "investigation_type": "MONEY_MULE",
            "prompt": (
                "For the money mule case CASE-JOHN-01, review entity John Doe with entity id "
                "ENTITY-JOHN-01. Case context: cash deposited at FI_A and transferred to "
                "external institutions over a two week period."
            ),
            "description": (
                "Discovery only: FI_A first probes the money mule lane over NATS, "
                "then sends explicit case discovery only to the responding cohort."
            ),
        },
        {
            "investigation_type": "TERRORIST_FINANCING",
            "prompt": (
                "For the terrorist financing case CASE-SAFIYA-01, review entity Safiya "
                "Rahman with entity id ENTITY-SAFIYA-01. Case context: inbound transfers "
                "from multiple remitters were followed by rapid cross-border movement "
                "linked to a suspected facilitation network."
            ),
            "description": (
                "Discovery only: FI_A first probes the terrorist financing lane over "
                "NATS, then sends explicit case discovery only to the responding cohort."
            ),
        },
    ]
    assert payload["aml_group_collaboration"] == [
        {
            "investigation_type": "MONEY_MULE",
            "prompt": (
                "For the money mule case CASE-JOHN-01, review entity John Doe with entity id "
                "ENTITY-JOHN-01. Case context: cash deposited at FI_A and transferred to "
                "external institutions over a two week period."
            ),
            "description": (
                "Discovery plus collaboration: probes the money mule lane first, then "
                "forms collaboration only from explicit accept responders."
            ),
        },
        {
            "investigation_type": "TERRORIST_FINANCING",
            "prompt": (
                "For the terrorist financing case CASE-SAFIYA-01, review entity Safiya "
                "Rahman with entity id ENTITY-SAFIYA-01. Case context: inbound transfers "
                "from multiple remitters were followed by rapid cross-border movement "
                "linked to a suspected facilitation network."
            ),
            "description": (
                "Discovery plus collaboration: probes the terrorist financing lane first, "
                "then forms collaboration only from explicit accept responders."
            ),
        },
    ]


def test_missing_required_prompt_fields_return_400() -> None:
    graph = AMLDiscoveryGraph(broadcast_func=_build_broadcast_func())
    app = create_app(graph)
    client = TestClient(app)

    response = client.post(
        "/agent/prompt",
        json={
            "prompt": (
                "For the money mule case CASE-JOHN-01, review entity John Doe with "
                "entity id ENTITY-JOHN-01."
            ),
            "investigation_type": "MONEY_MULE",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing required discovery fields: case_context"


def test_mismatched_prompt_and_request_investigation_type_returns_400() -> None:
    graph = AMLDiscoveryGraph(broadcast_func=_build_broadcast_func())
    app = create_app(graph)
    client = TestClient(app)

    response = client.post(
        "/agent/prompt",
        json={
            "prompt": (
                "For the money mule case CASE-JOHN-01, review entity John Doe with "
                "entity id ENTITY-JOHN-01. Case context: cash deposited at FI_A and "
                "transferred to external institutions over a two week period."
            ),
            "investigation_type": "TERRORIST_FINANCING",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Explicit investigation_type does not match the investigation type found in the prompt."
    )


def test_disabled_directory_row_blocks_responder_route(
    tmp_path: Path,
    prompt_case: dict[str, object],
) -> None:
    source_path = AML_DIR / "data" / "counterparty_directory.csv"
    target_path = tmp_path / "counterparty_directory.csv"
    df = pd.read_csv(source_path)
    disabled_institution_id = str(prompt_case["expected_candidates"][-1])
    df.loc[
        (df["institution_id"] == disabled_institution_id) & (df["transport"] == "A2A"),
        "enabled",
    ] = False
    df.to_csv(target_path, index=False)

    graph = AMLDiscoveryGraph(broadcast_func=_build_broadcast_func(directory_path=str(target_path)))
    app = create_app(graph)
    client = TestClient(app)

    response = client.post(
        "/agent/prompt",
        json={
            "prompt": prompt_case["prompt"],
            "investigation_type": prompt_case["investigation_type"],
        },
    )

    assert response.status_code == 400
    assert "Directory route is disabled" in response.json()["detail"]


def test_directory_endpoints_are_used_for_routing(prompt_case: dict[str, object]) -> None:
    capture_routes: list[str] = []
    graph = AMLDiscoveryGraph(broadcast_func=_build_broadcast_func(capture_routes=capture_routes))
    app = create_app(graph)
    client = TestClient(app)

    response = client.post(
        "/agent/prompt",
        json={
            "prompt": prompt_case["prompt"],
            "investigation_type": prompt_case["investigation_type"],
        },
    )

    assert response.status_code == 200
    assert capture_routes == [
        f"http://127.0.0.1:{9119 + index}"
        for index, institution_id in enumerate(("FI_B", "FI_C", "FI_D", "FI_E", "FI_F"), start=1)
        if institution_id in prompt_case["expected_candidates"]
    ]
