from __future__ import annotations

from pathlib import Path

import pytest

from aml314b.common.channeling import (
    InvestigationType,
    build_lane_scoped_topic,
    describe_investigation_lane,
    normalize_investigation_type,
)
from aml314b.common.enforcement import PlaceholderEnforcementLayer
from aml314b.common.probing import LaneProbeResponse
from aml314b.common.schemas import DiscoveryRequest
from aml314b.common.step_events import StepEventBuffer
from aml314b.common.stores import (
    ActiveInvestigationsStore,
    CuratedInvestigativeContextStore,
    KnownHighRiskEntitiesStore,
    LaneSubscriptionStore,
)
from aml314b.fi_a.graph.tools import broadcast_discovery, run_discovery_and_collaboration
from aml314b.institutions.common.collaboration_agent import InstitutionCollaborationAgent
from aml314b.institutions.common.discovery_agent import InstitutionDiscoveryAgent
from aml314b.institutions.common.runtime import build_slim_lane_registrations
from aml314b.institutions.fi_b.card import AGENT_CARD as FI_B_CARD

LUNGO_DIR = Path(__file__).resolve().parents[2]
AML_DIR = LUNGO_DIR / "aml314b"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _load_case(case_id: str, investigation_type: str):
    return ActiveInvestigationsStore(
        AML_DIR / "fi_a" / "data" / "active_investigations.csv"
    ).get_case(case_id, investigation_type)


def _load_supported_investigation_types(institution_slug: str):
    return tuple(
        LaneSubscriptionStore(
            AML_DIR / "institutions" / institution_slug / "data" / "lane_subscriptions.csv"
        ).list_supported_investigation_types()
    )


def _build_agents(*, transport_name: str):
    institutions: dict[str, dict[str, object]] = {}
    for institution_slug in ("fi_b", "fi_c", "fi_d", "fi_e", "fi_f"):
        institution_id = institution_slug.upper()
        enforcement = PlaceholderEnforcementLayer(
            logger_name=f"test.aml314b.{institution_slug}.{transport_name.lower()}"
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
                transport_name=transport_name,
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
                transport_name=transport_name,
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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("money mule", InvestigationType.MONEY_MULE),
        ("MONEY_MULE", InvestigationType.MONEY_MULE),
        ("terrorist financing", InvestigationType.TERRORIST_FINANCING),
        ("TERRORIST_FINANCING", InvestigationType.TERRORIST_FINANCING),
    ],
)
def test_normalize_investigation_type_accepts_supported_labels(
    value: str,
    expected: InvestigationType,
) -> None:
    assert normalize_investigation_type(value) == expected


def test_normalize_investigation_type_rejects_unsupported_labels() -> None:
    with pytest.raises(ValueError, match="Unsupported investigation_type"):
        normalize_investigation_type("fraud")


def test_step_event_buffer_filters_by_investigation_type_and_lane() -> None:
    buffer = StepEventBuffer()
    buffer.append_raw(
        case_id="CASE-1",
        investigation_type="MONEY_MULE",
        transport_lane="aml314b.money_mule",
        step_name="discovery_request_created",
        message="money mule event",
    )
    buffer.append_raw(
        case_id="CASE-1",
        investigation_type="TERRORIST_FINANCING",
        transport_lane="aml314b.terrorist_financing",
        step_name="discovery_request_created",
        message="terrorist financing event",
    )

    money_mule_events = buffer.get_since(
        case_id="CASE-1",
        investigation_type="MONEY_MULE",
        transport_lane="aml314b.money_mule",
    )
    terrorist_financing_events = buffer.get_since(
        case_id="CASE-1",
        investigation_type="TERRORIST_FINANCING",
        transport_lane="aml314b.terrorist_financing",
    )

    assert [event["message"] for event in money_mule_events] == ["money mule event"]
    assert [event["message"] for event in terrorist_financing_events] == [
        "terrorist financing event"
    ]


@pytest.mark.anyio
async def test_a2a_back_to_back_runs_preserve_investigation_type_and_participants() -> None:
    institutions = _build_agents(transport_name="A2A")

    async def discovery_sender(request, route):
        return await institutions[route.institution_id]["discovery"].evaluate_request(request)

    async def collaboration_sender(request, route):
        return await institutions[route.institution_id]["collaboration"].contribute(request)

    john_case = _load_case("CASE-JOHN-01", "MONEY_MULE")
    safiya_case = _load_case("CASE-SAFIYA-01", "TERRORIST_FINANCING")

    money_mule_discovery, money_mule_collaboration = await run_discovery_and_collaboration(
        "MONEY_MULE",
        john_case.case_id,
        john_case.entity_id,
        john_case.entity_name,
        john_case.activity_summary or "",
        discovery_sender=discovery_sender,
        collaboration_sender=collaboration_sender,
        probe_collector=_build_probe_collector(),
        directory_path=str(AML_DIR / "data" / "counterparty_directory.csv"),
        active_investigations_path=str(AML_DIR / "fi_a" / "data" / "active_investigations.csv"),
        transport_name="A2A",
    )
    terrorist_financing_discovery, terrorist_financing_collaboration = (
        await run_discovery_and_collaboration(
            "TERRORIST_FINANCING",
            safiya_case.case_id,
            safiya_case.entity_id,
            safiya_case.entity_name,
            safiya_case.activity_summary or "",
            discovery_sender=discovery_sender,
            collaboration_sender=collaboration_sender,
            probe_collector=_build_probe_collector(),
            directory_path=str(AML_DIR / "data" / "counterparty_directory.csv"),
            active_investigations_path=str(AML_DIR / "fi_a" / "data" / "active_investigations.csv"),
            transport_name="A2A",
        )
    )

    assert money_mule_discovery.investigation_type == "MONEY_MULE"
    assert money_mule_discovery.transport_lane is None
    assert money_mule_discovery.candidate_institutions == ["FI_B", "FI_C", "FI_D", "FI_E"]
    assert money_mule_discovery.accepted_institutions == ["FI_B", "FI_C", "FI_D"]
    assert [
        participant.institution_id for participant in money_mule_collaboration.participants
    ] == ["FI_A", "FI_B", "FI_C", "FI_D"]

    assert terrorist_financing_discovery.investigation_type == "TERRORIST_FINANCING"
    assert terrorist_financing_discovery.transport_lane is None
    assert terrorist_financing_discovery.candidate_institutions == ["FI_B", "FI_C", "FI_D", "FI_F"]
    assert terrorist_financing_discovery.accepted_institutions == ["FI_C", "FI_F"]
    assert [
        participant.institution_id
        for participant in terrorist_financing_collaboration.participants
    ] == ["FI_A", "FI_C", "FI_F"]


@pytest.mark.anyio
async def test_slim_discovery_results_use_distinct_transport_lanes() -> None:
    institutions = _build_agents(transport_name="SLIM")

    async def discovery_sender(request, route):
        return await institutions[route.institution_id]["discovery"].evaluate_request(request)

    john_case = _load_case("CASE-JOHN-01", "MONEY_MULE")
    safiya_case = _load_case("CASE-SAFIYA-01", "TERRORIST_FINANCING")

    money_mule_result = await broadcast_discovery(
        "MONEY_MULE",
        john_case.case_id,
        john_case.entity_id,
        john_case.entity_name,
        john_case.activity_summary or "",
        sender=discovery_sender,
        probe_collector=_build_probe_collector(),
        directory_path=str(AML_DIR / "data" / "counterparty_directory.csv"),
        active_investigations_path=str(AML_DIR / "fi_a" / "data" / "active_investigations.csv"),
        transport_name="SLIM",
    )
    terrorist_financing_result = await broadcast_discovery(
        "TERRORIST_FINANCING",
        safiya_case.case_id,
        safiya_case.entity_id,
        safiya_case.entity_name,
        safiya_case.activity_summary or "",
        sender=discovery_sender,
        probe_collector=_build_probe_collector(),
        directory_path=str(AML_DIR / "data" / "counterparty_directory.csv"),
        active_investigations_path=str(AML_DIR / "fi_a" / "data" / "active_investigations.csv"),
        transport_name="SLIM",
    )

    assert money_mule_result.candidate_institutions == ["FI_B", "FI_C", "FI_D", "FI_E"]
    assert terrorist_financing_result.candidate_institutions == ["FI_B", "FI_C", "FI_D", "FI_F"]
    assert money_mule_result.transport_lane == "aml314b.money_mule"
    assert terrorist_financing_result.transport_lane == "aml314b.terrorist_financing"
    assert money_mule_result.transport_lane != terrorist_financing_result.transport_lane


def test_slim_lane_topics_are_distinct() -> None:
    registrations = build_slim_lane_registrations(
        FI_B_CARD,
        "FI_B",
        AML_DIR / "institutions" / "fi_b" / "data",
        port=9120,
    )
    topics = {registration.descriptor.investigation_type.value: registration.topic for registration in registrations}

    assert topics["MONEY_MULE"].endswith(".money_mule")
    assert topics["TERRORIST_FINANCING"].endswith(".terrorist_financing")
    assert topics["MONEY_MULE"] != topics["TERRORIST_FINANCING"]
    assert topics["MONEY_MULE"] == build_lane_scoped_topic(
        topics["MONEY_MULE"].removesuffix(".money_mule"),
        "MONEY_MULE",
    )


@pytest.mark.anyio
async def test_slim_lane_bound_responder_rejects_misrouted_payload() -> None:
    money_mule_lane = describe_investigation_lane("MONEY_MULE")
    terrorist_financing_lane = describe_investigation_lane("TERRORIST_FINANCING")
    store = KnownHighRiskEntitiesStore(
        AML_DIR / "institutions" / "fi_b" / "data" / "known_high_risk_entities.csv"
    )
    agent = InstitutionDiscoveryAgent(
        institution_id="FI_B",
        known_high_risk_store=store,
        enforcement=PlaceholderEnforcementLayer(),
        transport_name="SLIM",
        expected_investigation_type="MONEY_MULE",
        expected_transport_lane=money_mule_lane.transport_lane,
    )
    case = _load_case("CASE-SAFIYA-01", "TERRORIST_FINANCING")
    request = DiscoveryRequest(
        requestor_institution_id="FI_A",
        target_institution_id="FI_B",
        investigation_type="TERRORIST_FINANCING",
        transport_lane=terrorist_financing_lane.transport_lane,
        case_id=case.case_id,
        entity_id=case.entity_id,
        entity_name=case.entity_name,
        case_context=case.activity_summary or "",
        time_window=case.to_time_window(),
    )

    with pytest.raises(ValueError, match="registered investigation lane"):
        await agent.evaluate_request(request)
