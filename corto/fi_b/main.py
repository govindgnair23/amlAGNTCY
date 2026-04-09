from __future__ import annotations

import logging

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

from aml314b.schemas import B314Request, B314Response
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
from aml314b.step_events import StepEventCollector
from config.config import (
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
from config.logging_config import setup_logging
from fi_b.agent import ResponderAgent
from fi_b.risk import DeterministicRiskClassifier, LLMRiskClassifier

load_dotenv()
setup_logging()
logger = logging.getLogger("corto.aml314b.fi_b.main")

app = FastAPI(title="FI-B Responder Agent")


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


@app.post("/aml314b/request", response_model=B314Response)
async def handle_314b_request(request: B314Request) -> B314Response:
    try:
        step_collector = StepEventCollector(case_id=request.case_id)
        response = await responder_agent.evaluate_request(
            request, step_collector=step_collector
        )
        payload = response.model_dump(mode="json")
        payload["step_events"] = step_collector.to_payloads()
        return JSONResponse(content=payload)
    except ValueError as exc:
        logger.exception("FI-B blocked request: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("FI-B failed to evaluate request: %s", exc)
        raise HTTPException(status_code=500, detail="Responder failure") from exc


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "institution": "FI-B"}


if __name__ == "__main__":
    uvicorn.run("fi_b.main:app", host=AML314B_RESPONDER_HOST, port=AML314B_RESPONDER_PORT, reload=True)
