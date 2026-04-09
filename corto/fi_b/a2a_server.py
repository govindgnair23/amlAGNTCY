from __future__ import annotations

import asyncio

from uvicorn import Config, Server
from dotenv import load_dotenv

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from agntcy_app_sdk.factory import AgntcyFactory
from agntcy_app_sdk.app_sessions import AppContainer
from agntcy_app_sdk.semantic.a2a.protocol import A2AProtocol

from config.config import (
    AML314B_ENABLE_TRACING,
    AML314B_MESSAGE_TRANSPORT,
    AML314B_TRANSPORT_SERVER_ENDPOINT,
    AML314B_RESPONDER_HOST,
    AML314B_RESPONDER_PORT,
    AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
    AML314B_CURATED_CONTEXT_PATH,
    AML314B_INTERNAL_INVESTIGATIONS_PATH,
    AML314B_USE_LLM_RISK_CLASSIFIER,
    AML314B_ENABLE_LAYERED_DISCLOSURE,
    AML314B_DISCLOSURE_AUDIT_PATH,
    AML314B_DISCLOSURE_POLICY_TEXT,
    AML314B_DISCLOSURE_FAIL_CLOSED,
    AML314B_DEFAULT_REQUESTER_INSTITUTION_ID,
    AML314B_DEFAULT_RESPONDER_INSTITUTION_ID,
)
from aml314b.enforcement import PlaceholderEnforcementLayer
from aml314b.enforcement_disclosure import (
    CumulativeDisclosureLayer,
    CumulativeLayerConfig,
    LLMDisclosureCritic,
    LayeredDisclosureEnforcer,
    DeterministicPolicyLayer,
    SemanticLayerConfig,
    SingleTurnSemanticLayer,
)
from aml314b.stores import (
    KnownHighRiskEntitiesStore,
    CuratedInvestigativeContextStore,
    InternalInvestigationsTriggerStore,
    DisclosureAuditStore,
)
from fi_b.agent import ResponderAgent
from fi_b.agent_executor import AMLResponderExecutor
from fi_b.card import AGENT_CARD
from fi_b.risk import DeterministicRiskClassifier, LLMRiskClassifier

load_dotenv()

factory = AgntcyFactory("corto.aml.fi_b", enable_tracing=AML314B_ENABLE_TRACING)


def _build_layered_disclosure_enforcer() -> LayeredDisclosureEnforcer:
    disclosure_store = DisclosureAuditStore(AML314B_DISCLOSURE_AUDIT_PATH)
    critic = LLMDisclosureCritic()
    return LayeredDisclosureEnforcer(
        deterministic_layer=DeterministicPolicyLayer(),
        semantic_layer=SingleTurnSemanticLayer(
            critic=critic,
            config=SemanticLayerConfig(
                policy_text=AML314B_DISCLOSURE_POLICY_TEXT,
                fail_closed=AML314B_DISCLOSURE_FAIL_CLOSED,
            ),
        ),
        cumulative_layer=CumulativeDisclosureLayer(
            critic=critic,
            audit_store=disclosure_store,
            config=CumulativeLayerConfig(
                policy_text=AML314B_DISCLOSURE_POLICY_TEXT,
                fail_closed=AML314B_DISCLOSURE_FAIL_CLOSED,
            ),
        ),
        audit_store=disclosure_store,
    )


async def main() -> None:
    enforcement_layer = PlaceholderEnforcementLayer(logger_name="corto.aml314b.fi_b.enforcement")
    known_store = KnownHighRiskEntitiesStore(AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH)
    curated_store = CuratedInvestigativeContextStore(AML314B_CURATED_CONTEXT_PATH)
    internal_store = InternalInvestigationsTriggerStore(AML314B_INTERNAL_INVESTIGATIONS_PATH)
    risk_classifier = (
        LLMRiskClassifier() if AML314B_USE_LLM_RISK_CLASSIFIER else DeterministicRiskClassifier()
    )
    layered_disclosure_enforcer = (
        _build_layered_disclosure_enforcer() if AML314B_ENABLE_LAYERED_DISCLOSURE else None
    )

    responder_agent = ResponderAgent(
        known_high_risk_store=known_store,
        curated_context_store=curated_store,
        enforcement=enforcement_layer,
        internal_investigations_store=internal_store,
        risk_classifier=risk_classifier,
        layered_disclosure_enforcer=layered_disclosure_enforcer,
        default_requester_institution_id=AML314B_DEFAULT_REQUESTER_INSTITUTION_ID,
        institution_id=AML314B_DEFAULT_RESPONDER_INSTITUTION_ID,
    )

    request_handler = DefaultRequestHandler(
        agent_executor=AMLResponderExecutor(responder_agent),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(agent_card=AGENT_CARD, http_handler=request_handler)

    if AML314B_MESSAGE_TRANSPORT == "A2A":
        config = Config(
            app=server.build(),
            host=AML314B_RESPONDER_HOST,
            port=AML314B_RESPONDER_PORT,
            loop="asyncio",
        )
        userver = Server(config)
        await userver.serve()
    else:
        transport = factory.create_transport(
            AML314B_MESSAGE_TRANSPORT,
            endpoint=AML314B_TRANSPORT_SERVER_ENDPOINT,
            name="default/default/" + A2AProtocol.create_agent_topic(AGENT_CARD),
        )
        app_session = factory.create_app_session()
        app_session.add_app_container(
            "aml-fi-b",
            AppContainer(
                server,
                transport=transport,
                topic=A2AProtocol.create_agent_topic(AGENT_CARD),
            ),
        )
        await app_session.start_session("aml-fi-b", keep_alive=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down gracefully on keyboard interrupt.")
    except Exception as exc:
        print(f"Error occurred: {exc}")
