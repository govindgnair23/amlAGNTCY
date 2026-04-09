from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException

from aml314b.enforcement import PlaceholderEnforcementLayer
from aml314b.enforcement_disclosure import (
    CumulativeDisclosureLayer,
    CumulativeLayerConfig,
    DisclosureCritic,
    LLMDisclosureCritic,
    LayeredDisclosureEnforcer,
    DeterministicPolicyLayer,
    SemanticLayerConfig,
    SingleTurnSemanticLayer,
)
from aml314b.schemas import B314Request, B314Response
from aml314b.stores import (
    ActiveInvestigationsStore,
    CounterpartyDirectoryStore,
    KnownHighRiskEntitiesStore,
    CuratedInvestigativeContextStore,
    RetrievedInformationStore,
    InternalInvestigationsTriggerStore,
    DisclosureAuditStore,
)
from config.config import (
    AML314B_ACTIVE_INVESTIGATIONS_PATH,
    AML314B_DIRECTORY_PATH,
    AML314B_RETRIEVED_INFORMATION_PATH,
    AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
    AML314B_CURATED_CONTEXT_PATH,
    AML314B_INTERNAL_INVESTIGATIONS_PATH,
    AML314B_REQUESTOR_CASE_LIMIT,
    AML314B_MESSAGE_TRANSPORT,
    AML314B_ENABLE_LAYERED_DISCLOSURE,
    AML314B_DISCLOSURE_AUDIT_PATH,
    AML314B_DISCLOSURE_POLICY_TEXT,
    AML314B_DISCLOSURE_FAIL_CLOSED,
    AML314B_DEFAULT_REQUESTER_INSTITUTION_ID,
    AML314B_DEFAULT_RESPONDER_INSTITUTION_ID,
)
from fi_a.agent import RequestorAgent
from fi_a import tools
from fi_b.agent import ResponderAgent
from fi_b.risk import DeterministicRiskClassifier


def _build_responder_app(agent: ResponderAgent) -> FastAPI:
    app = FastAPI(title="FI-B In-Process Responder")

    @app.post("/aml314b/request", response_model=B314Response)
    async def handle_request(request: B314Request) -> B314Response:
        try:
            return await agent.evaluate_request(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


async def run_bilateral_demo(
    case_id: str | None = None,
    *,
    active_investigations_path: str = AML314B_ACTIVE_INVESTIGATIONS_PATH,
    directory_path: str = AML314B_DIRECTORY_PATH,
    retrieved_information_path: str = AML314B_RETRIEVED_INFORMATION_PATH,
    known_high_risk_entities_path: str = AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
    curated_context_path: str = AML314B_CURATED_CONTEXT_PATH,
    internal_investigations_path: str = AML314B_INTERNAL_INVESTIGATIONS_PATH,
    case_limit: int | None = AML314B_REQUESTOR_CASE_LIMIT,
    layered_disclosure_enabled: bool = False,
    disclosure_audit_path: str = AML314B_DISCLOSURE_AUDIT_PATH,
    disclosure_policy_text: str = AML314B_DISCLOSURE_POLICY_TEXT,
    disclosure_fail_closed: bool = AML314B_DISCLOSURE_FAIL_CLOSED,
    disclosure_critic: DisclosureCritic | None = None,
    requester_institution_id: str = AML314B_DEFAULT_REQUESTER_INSTITUTION_ID,
    responder_institution_id: str = AML314B_DEFAULT_RESPONDER_INSTITUTION_ID,
) -> dict[str, Any]:
    """Run the bilateral AML flow in-process for deterministic testing."""
    requestor_enforcement = PlaceholderEnforcementLayer(
        logger_name="corto.aml314b.fi_a.enforcement"
    )
    responder_enforcement = PlaceholderEnforcementLayer(
        logger_name="corto.aml314b.fi_b.enforcement"
    )

    active_store = ActiveInvestigationsStore(active_investigations_path)
    directory_store = CounterpartyDirectoryStore(directory_path)
    retrieved_store = RetrievedInformationStore(retrieved_information_path)
    known_store = KnownHighRiskEntitiesStore(known_high_risk_entities_path)
    curated_store = CuratedInvestigativeContextStore(curated_context_path)
    internal_store = InternalInvestigationsTriggerStore(internal_investigations_path)

    disclosure_store: DisclosureAuditStore | None = None
    layered_disclosure_enforcer: LayeredDisclosureEnforcer | None = None
    if layered_disclosure_enabled:
        disclosure_store = DisclosureAuditStore(disclosure_audit_path)
        critic = disclosure_critic or LLMDisclosureCritic()
        layered_disclosure_enforcer = LayeredDisclosureEnforcer(
            deterministic_layer=DeterministicPolicyLayer(),
            semantic_layer=SingleTurnSemanticLayer(
                critic=critic,
                config=SemanticLayerConfig(
                    policy_text=disclosure_policy_text,
                    fail_closed=disclosure_fail_closed,
                ),
            ),
            cumulative_layer=CumulativeDisclosureLayer(
                critic=critic,
                audit_store=disclosure_store,
                config=CumulativeLayerConfig(
                    policy_text=disclosure_policy_text,
                    fail_closed=disclosure_fail_closed,
                ),
            ),
            audit_store=disclosure_store,
        )

    responder_agent = ResponderAgent(
        known_high_risk_store=known_store,
        curated_context_store=curated_store,
        enforcement=responder_enforcement,
        internal_investigations_store=internal_store,
        risk_classifier=DeterministicRiskClassifier(),
        layered_disclosure_enforcer=layered_disclosure_enforcer,
        default_requester_institution_id=requester_institution_id,
        institution_id=responder_institution_id,
    )
    responder_app = _build_responder_app(responder_agent)

    transport = httpx.ASGITransport(app=responder_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://fi-b.local") as client:
        requestor_agent = RequestorAgent(
            active_store=active_store,
            retrieved_store=retrieved_store,
            directory_store=directory_store,
            enforcement=requestor_enforcement,
            send_request=lambda request, _route: tools.send_314b_request(client, request),
            transport_name=AML314B_MESSAGE_TRANSPORT,
        )

        if case_id:
            results = [await requestor_agent.run_case(case_id)]
        else:
            results = await requestor_agent.run_active_cases(limit=case_limit)

    retrieved_df = retrieved_store.read_all()
    internal_df = internal_store.read_all()
    disclosure_df = (
        disclosure_store.read_all() if disclosure_store is not None else []
    )
    return {
        "cases_processed": len(results),
        "results": [result.to_dict() for result in results],
        "requestor_enforcement_events": [event.__dict__ for event in requestor_enforcement.get_events()],
        "responder_enforcement_events": [event.__dict__ for event in responder_enforcement.get_events()],
        "retrieved_information_rows": retrieved_df.to_dict(orient="records"),
        "internal_investigations_rows": internal_df.to_dict(orient="records"),
        "disclosure_audit_rows": (
            disclosure_df.to_dict(orient="records") if hasattr(disclosure_df, "to_dict") else []
        ),
        "retrieved_information_path": retrieved_information_path,
        "internal_investigations_path": internal_investigations_path,
        "disclosure_audit_path": disclosure_audit_path,
        "layered_disclosure_enabled": layered_disclosure_enabled,
    }


def run_bilateral_demo_sync(case_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return asyncio.run(run_bilateral_demo(case_id=case_id, **kwargs))
