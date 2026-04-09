from __future__ import annotations

from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from config.config import AML314B_RESPONDER_HOST, AML314B_RESPONDER_PORT

AGENT_SKILL = AgentSkill(
    id="aml_314b_response",
    name="AML 314(b) Response",
    description="Evaluates 314(b) requests and returns bounded responses for FI-B.",
    tags=["aml", "314b", "fi_b"],
    examples=[
        "Check John Doe activity against known high risk entities",
        "Return a bounded response for a 314(b) request",
    ],
)

AGENT_CARD = AgentCard(
    name="AML 314(b) Responder",
    id="aml-314b-responder",
    description="FI-B responder agent for AML 314(b) bilateral communication.",
    url=f"http://{AML314B_RESPONDER_HOST}:{AML314B_RESPONDER_PORT}/",
    version="1.0.0",
    defaultInputModes=["text"],
    defaultOutputModes=["text"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[AGENT_SKILL],
    supportsAuthenticatedExtendedCard=False,
)
