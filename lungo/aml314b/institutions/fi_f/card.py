from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from config.config import AML314B_DISCOVERY_RESPONDER_BASE_PORT, AML314B_RESPONDER_HOST

AGENT_CARD = AgentCard(
    name="FI_F Discovery Responder",
    id="fi_f-discovery-responder",
    description="Deterministic AML discovery responder for FI_F.",
    url=f"http://{AML314B_RESPONDER_HOST}:{AML314B_DISCOVERY_RESPONDER_BASE_PORT + 4}",
    version="1.0.0",
    defaultInputModes=["text"],
    defaultOutputModes=["text"],
    capabilities=AgentCapabilities(streaming=False),
    skills=[
        AgentSkill(
            id="evaluate_discovery_request",
            name="Evaluate Discovery Request",
            description="Evaluates AML discovery requests for FI_F.",
            tags=["aml", "discovery", "314b"],
            examples=["Evaluate ENTITY-JOHN-01 for CASE-JOHN-01."],
        )
    ],
    supportsAuthenticatedExtendedCard=False,
)
