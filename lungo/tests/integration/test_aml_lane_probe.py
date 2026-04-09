from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest

from aml314b.common.enforcement import PlaceholderEnforcementLayer
from aml314b.common.probing import (
    LaneProbeNatsClient,
    LaneProbeRequest,
    LaneProbeResponderRuntime,
)
from aml314b.common.stores import (
    CuratedInvestigativeContextStore,
    KnownHighRiskEntitiesStore,
    LaneSubscriptionStore,
)
from aml314b.fi_a.graph.tools import run_discovery_and_collaboration
from aml314b.institutions.common.collaboration_agent import InstitutionCollaborationAgent
from aml314b.institutions.common.discovery_agent import InstitutionDiscoveryAgent

LUNGO_DIR = Path(__file__).resolve().parents[2]
AML_DIR = LUNGO_DIR / "aml314b"
INSTITUTION_SLUGS = ("fi_b", "fi_c", "fi_d", "fi_e", "fi_f")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def nats_endpoint() -> str:
    host_port = _reserve_port()
    container_name = f"lungo-aml314b-test-nats-{uuid4().hex[:8]}"
    cmd = [
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        container_name,
        "-p",
        f"{host_port}:4222",
        "nats:latest",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"Docker-backed NATS is unavailable: {exc}")
    try:
        _wait_for_port(host_port)
        yield f"nats://127.0.0.1:{host_port}"
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            check=False,
            capture_output=True,
            text=True,
        )


def _reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, *, timeout_s: float = 10.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise TimeoutError(f"NATS test server on port {port} did not become ready.")


def _load_supported_investigation_types(institution_slug: str):
    return tuple(
        LaneSubscriptionStore(
            AML_DIR / "institutions" / institution_slug / "data" / "lane_subscriptions.csv"
        ).list_supported_investigation_types()
    )


def _build_agents():
    institutions: dict[str, dict[str, object]] = {}
    for institution_slug in INSTITUTION_SLUGS:
        institution_id = institution_slug.upper()
        enforcement = PlaceholderEnforcementLayer(
            logger_name=f"test.aml314b.{institution_slug}.probe"
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


def _build_probe_runtimes(nats_endpoint: str) -> list[LaneProbeResponderRuntime]:
    return [
        LaneProbeResponderRuntime(
            institution_id=institution_slug.upper(),
            supported_investigation_types=_load_supported_investigation_types(
                institution_slug
            ),
            endpoint=nats_endpoint,
        )
        for institution_slug in INSTITUTION_SLUGS
    ]


@pytest.mark.parametrize(
    ("institution_id", "expected_supported"),
    [
        ("FI_B", ["MONEY_MULE", "TERRORIST_FINANCING"]),
        ("FI_C", ["MONEY_MULE", "TERRORIST_FINANCING"]),
        ("FI_D", ["MONEY_MULE", "TERRORIST_FINANCING"]),
        ("FI_E", ["MONEY_MULE"]),
        ("FI_F", ["TERRORIST_FINANCING"]),
    ],
)
def test_lane_subscription_loading_matches_seeded_membership(
    institution_id: str,
    expected_supported: list[str],
) -> None:
    institution_slug = institution_id.lower()
    store = LaneSubscriptionStore(
        AML_DIR / "institutions" / institution_slug / "data" / "lane_subscriptions.csv"
    )

    assert [item.value for item in store.list_supported_investigation_types()] == expected_supported


def test_lane_probe_contract_excludes_case_specific_fields() -> None:
    request = LaneProbeRequest(
        requestor_institution_id="FI_A",
        investigation_type="MONEY_MULE",
    )
    payload = request.model_dump(mode="json")

    assert set(payload) == {
        "probe_id",
        "requestor_institution_id",
        "investigation_type",
        "sent_at",
    }
    assert "case_id" not in payload
    assert "entity_id" not in payload
    assert "entity_name" not in payload
    assert "case_context" not in payload


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("investigation_type", "expected_responders"),
    [
        ("MONEY_MULE", ["FI_B", "FI_C", "FI_D", "FI_E"]),
        ("TERRORIST_FINANCING", ["FI_B", "FI_C", "FI_D", "FI_F"]),
    ],
)
async def test_nats_lane_probe_returns_only_configured_members(
    nats_endpoint: str,
    investigation_type: str,
    expected_responders: list[str],
) -> None:
    runtimes = _build_probe_runtimes(nats_endpoint)
    client = LaneProbeNatsClient(endpoint=nats_endpoint, response_timeout_ms=250)
    try:
        for runtime in runtimes:
            await runtime.start()
        responses = await client.collect(
            LaneProbeRequest(
                requestor_institution_id="FI_A",
                investigation_type=investigation_type,
            )
        )
    finally:
        for runtime in reversed(runtimes):
            await runtime.close()

    assert sorted(response.responder_institution_id for response in responses) == expected_responders


@pytest.mark.anyio
@pytest.mark.parametrize(
    (
        "investigation_type",
        "case_id",
        "entity_id",
        "entity_name",
        "case_context",
        "expected_candidates",
        "expected_accepted",
        "expected_declined",
        "expected_participants",
    ),
    [
        (
            "MONEY_MULE",
            "CASE-JOHN-01",
            "ENTITY-JOHN-01",
            "John Doe",
            "cash deposited at FI_A and transferred to external institutions over a two week period.",
            ["FI_B", "FI_C", "FI_D", "FI_E"],
            ["FI_B", "FI_C", "FI_D"],
            ["FI_E"],
            ["FI_A", "FI_B", "FI_C", "FI_D"],
        ),
        (
            "TERRORIST_FINANCING",
            "CASE-SAFIYA-01",
            "ENTITY-SAFIYA-01",
            "Safiya Rahman",
            "inbound transfers from multiple remitters were followed by rapid cross-border movement linked to a suspected facilitation network.",
            ["FI_B", "FI_C", "FI_D", "FI_F"],
            ["FI_C", "FI_F"],
            ["FI_B", "FI_D"],
            ["FI_A", "FI_C", "FI_F"],
        ),
    ],
)
async def test_probe_driven_discovery_and_collaboration_only_use_probe_candidates(
    nats_endpoint: str,
    investigation_type: str,
    case_id: str,
    entity_id: str,
    entity_name: str,
    case_context: str,
    expected_candidates: list[str],
    expected_accepted: list[str],
    expected_declined: list[str],
    expected_participants: list[str],
) -> None:
    institutions = _build_agents()
    runtimes = _build_probe_runtimes(nats_endpoint)
    probe_client = LaneProbeNatsClient(endpoint=nats_endpoint, response_timeout_ms=250)

    async def discovery_sender(request, route):
        return await institutions[route.institution_id]["discovery"].evaluate_request(request)

    async def collaboration_sender(request, route):
        return await institutions[route.institution_id]["collaboration"].contribute(request)

    try:
        for runtime in runtimes:
            await runtime.start()
        discovery_result, collaboration_result = await run_discovery_and_collaboration(
            investigation_type,
            case_id,
            entity_id,
            entity_name,
            case_context,
            discovery_sender=discovery_sender,
            collaboration_sender=collaboration_sender,
            probe_collector=probe_client.collect,
            directory_path=str(AML_DIR / "data" / "counterparty_directory.csv"),
            active_investigations_path=str(AML_DIR / "fi_a" / "data" / "active_investigations.csv"),
            transport_name="A2A",
        )
    finally:
        for runtime in reversed(runtimes):
            await runtime.close()

    assert discovery_result.candidate_institutions == expected_candidates
    assert discovery_result.candidate_response_count == len(expected_candidates)
    assert discovery_result.candidate_resolution_source == "NATS_LANE_PROBE"
    assert sorted(response.responder_institution_id for response in discovery_result.responses) == expected_candidates
    assert discovery_result.accepted_institutions == expected_accepted
    assert discovery_result.declined_institutions == expected_declined
    assert [
        participant.institution_id for participant in collaboration_result.participants
    ] == expected_participants
