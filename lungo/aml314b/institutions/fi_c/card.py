from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from config.config import AML314B_DISCOVERY_RESPONDER_BASE_PORT, AML314B_RESPONDER_HOST

AGENT_CARD = AgentCard(
    name="FI_C Discovery Responder",
    id="fi_c-discovery-responder",
    description="Deterministic AML discovery responder for FI_C.",
    url=f"http://{AML314B_RESPONDER_HOST}:{AML314B_DISCOVERY_RESPONDER_BASE_PORT + 1}",
    version="1.0.0",
    defaultInputModes=["text"],
    defaultOutputModes=["text"],
    capabilities=AgentCapabilities(streaming=False),
    skills=[
        AgentSkill(
            id="evaluate_discovery_request",
            name="Evaluate Discovery Request",
            description="Evaluates AML discovery requests for FI_C.",
            tags=["aml", "discovery", "314b"],
            examples=["Evaluate ENTITY-JOHN-01 for CASE-JOHN-01."],
        )
    ],
    supportsAuthenticatedExtendedCard=False,
)
