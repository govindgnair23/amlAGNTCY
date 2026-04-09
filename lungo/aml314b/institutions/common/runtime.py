from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from uvicorn import Config, Server

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from agntcy_app_sdk.app_sessions import AppContainer
from agntcy_app_sdk.factory import AgntcyFactory
from agntcy_app_sdk.semantic.a2a.protocol import A2AProtocol

from aml314b.common.channeling import (
    InvestigationLaneDescriptor,
    InvestigationType,
    build_lane_scoped_topic,
    describe_investigation_lane,
)
from aml314b.common.enforcement import PlaceholderEnforcementLayer
from aml314b.common.probing import LaneProbeResponderRuntime
from aml314b.common.stores import (
    CuratedInvestigativeContextStore,
    KnownHighRiskEntitiesStore,
    LaneSubscriptionStore,
)
from aml314b.institutions.common.agent_executor import AMLResponderExecutor
from aml314b.institutions.common.collaboration_agent import InstitutionCollaborationAgent
from aml314b.institutions.common.discovery_agent import InstitutionDiscoveryAgent
from config.config import (
    AML314B_MESSAGE_TRANSPORT,
    AML314B_PROBE_NATS_ENDPOINT,
    AML314B_PROBE_TRANSPORT,
    AML314B_RESPONDER_HOST,
    AML314B_TRANSPORT_SERVER_ENDPOINT,
)

load_dotenv()


@dataclass(frozen=True)
class ResponderLaneRegistration:
    session_name: str
    descriptor: InvestigationLaneDescriptor
    topic: str
    server: A2AStarletteApplication


def _card_with_runtime_url(agent_card, *, host: str, port: int):
    if getattr(agent_card, "url", ""):
        return agent_card
    return agent_card.model_copy(update={"url": f"http://{host}:{port}"})


def _load_responder_stores(data_dir: Path) -> tuple[
    KnownHighRiskEntitiesStore,
    CuratedInvestigativeContextStore,
]:
    known_store = KnownHighRiskEntitiesStore(data_dir / "known_high_risk_entities.csv")
    context_store = CuratedInvestigativeContextStore(data_dir / "curated_investigative_context.csv")
    return known_store, context_store


def _load_lane_subscription_store(data_dir: Path) -> LaneSubscriptionStore:
    return LaneSubscriptionStore(data_dir / "lane_subscriptions.csv")


def _build_responder_application(
    agent_card,
    institution_id: str,
    *,
    known_store: KnownHighRiskEntitiesStore,
    context_store: CuratedInvestigativeContextStore,
    port: int,
    transport_name: str,
    supported_investigation_types: tuple[InvestigationType, ...] | None = None,
    investigation_type: InvestigationType | None = None,
    transport_lane: str | None = None,
):
    enforcement = PlaceholderEnforcementLayer(
        logger_name=f"lungo.aml314b.{institution_id.lower()}.enforcement"
    )
    agent_card = _card_with_runtime_url(
        agent_card,
        host=AML314B_RESPONDER_HOST,
        port=port,
    )
    discovery_agent = InstitutionDiscoveryAgent(
        institution_id=institution_id,
        known_high_risk_store=known_store,
        enforcement=enforcement,
        transport_name=transport_name,
        supported_investigation_types=supported_investigation_types,
        expected_investigation_type=investigation_type,
        expected_transport_lane=transport_lane,
    )
    collaboration_agent = InstitutionCollaborationAgent(
        institution_id=institution_id,
        investigative_context_store=context_store,
        enforcement=enforcement,
        transport_name=transport_name,
        supported_investigation_types=supported_investigation_types,
        expected_investigation_type=investigation_type,
        expected_transport_lane=transport_lane,
    )
    request_handler = DefaultRequestHandler(
        agent_executor=AMLResponderExecutor(
            discovery_agent,
            collaboration_agent,
            transport_name=transport_name,
        ),
        task_store=InMemoryTaskStore(),
    )
    return A2AStarletteApplication(agent_card=agent_card, http_handler=request_handler)


def build_responder_http_app(agent_card, institution_id: str, data_dir: Path, *, port: int):
    known_store, context_store = _load_responder_stores(data_dir)
    lane_store = _load_lane_subscription_store(data_dir)
    return _build_responder_application(
        agent_card,
        institution_id,
        known_store=known_store,
        context_store=context_store,
        port=port,
        transport_name="A2A",
        supported_investigation_types=tuple(lane_store.list_supported_investigation_types()),
    )


def build_slim_lane_registrations(
    agent_card,
    institution_id: str,
    data_dir: Path,
    *,
    port: int,
) -> list[ResponderLaneRegistration]:
    known_store, context_store = _load_responder_stores(data_dir)
    lane_store = _load_lane_subscription_store(data_dir)
    runtime_card = _card_with_runtime_url(
        agent_card,
        host=AML314B_RESPONDER_HOST,
        port=port,
    )
    base_topic = A2AProtocol.create_agent_topic(runtime_card)
    registrations: list[ResponderLaneRegistration] = []
    supported_investigation_types = tuple(lane_store.list_supported_investigation_types())
    for descriptor in (
        describe_investigation_lane(investigation_type)
        for investigation_type in supported_investigation_types
    ):
        topic = build_lane_scoped_topic(base_topic, descriptor.investigation_type)
        server = _build_responder_application(
            runtime_card,
            institution_id,
            known_store=known_store,
            context_store=context_store,
            port=port,
            transport_name=AML314B_MESSAGE_TRANSPORT,
            supported_investigation_types=supported_investigation_types,
            investigation_type=descriptor.investigation_type,
            transport_lane=descriptor.transport_lane,
        )
        registrations.append(
            ResponderLaneRegistration(
                session_name=f"{institution_id.lower()}_{descriptor.lane_key}",
                descriptor=descriptor,
                topic=topic,
                server=server,
            )
        )
    return registrations


def build_lane_probe_runtime(
    institution_id: str,
    data_dir: Path,
) -> LaneProbeResponderRuntime | None:
    if AML314B_PROBE_TRANSPORT != "NATS":
        return None
    lane_store = _load_lane_subscription_store(data_dir)
    supported_investigation_types = tuple(lane_store.list_supported_investigation_types())
    return LaneProbeResponderRuntime(
        institution_id=institution_id,
        supported_investigation_types=supported_investigation_types,
        endpoint=AML314B_PROBE_NATS_ENDPOINT,
    )


async def run_responder_server(
    *,
    app_name: str,
    institution_id: str,
    agent_card,
    data_dir: Path,
    port: int,
) -> None:
    factory = AgntcyFactory(app_name, enable_tracing=True)
    agent_card = _card_with_runtime_url(
        agent_card,
        host=AML314B_RESPONDER_HOST,
        port=port,
    )
    server = build_responder_http_app(agent_card, institution_id, data_dir, port=port)
    probe_runtime = build_lane_probe_runtime(institution_id, data_dir)

    if AML314B_MESSAGE_TRANSPORT == "A2A":
        config = Config(app=server.build(), host=AML314B_RESPONDER_HOST, port=port, loop="asyncio")
        userver = Server(config)
        if probe_runtime is not None:
            await probe_runtime.start()
        try:
            await userver.serve()
        finally:
            if probe_runtime is not None:
                await probe_runtime.close()
        return

    app_session = factory.create_app_session()
    registrations = build_slim_lane_registrations(agent_card, institution_id, data_dir, port=port)
    for registration in registrations:
        transport = factory.create_transport(
            AML314B_MESSAGE_TRANSPORT,
            endpoint=AML314B_TRANSPORT_SERVER_ENDPOINT,
            name=f"default/default/{registration.topic}",
        )
        app_session.add_app_container(
            registration.session_name,
            AppContainer(
                registration.server,
                transport=transport,
                topic=registration.topic,
            ),
        )
    if probe_runtime is not None:
        await probe_runtime.start()
    try:
        await asyncio.gather(
            *[
                app_session.start_session(registration.session_name, keep_alive=True)
                for registration in registrations
            ]
        )
    finally:
        if probe_runtime is not None:
            await probe_runtime.close()


def run_responder_sync(
    *,
    app_name: str,
    institution_id: str,
    agent_card,
    data_dir: Path,
    port: int,
) -> None:
    asyncio.run(
        run_responder_server(
            app_name=app_name,
            institution_id=institution_id,
            agent_card=agent_card,
            data_dir=data_dir,
            port=port,
        )
    )
