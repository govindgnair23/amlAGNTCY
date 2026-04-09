from __future__ import annotations

from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from config.config import AML314B_REQUESTOR_HOST, AML314B_REQUESTOR_PORT

AGENT_SKILL = AgentSkill(
    id="aml_314b_request",
    name="AML 314(b) Request",
    description="Initiates 314(b) requests on behalf of FI-A.",
    tags=["aml", "314b", "fi_a"],
    examples=[
        "Send a 314(b) request for John Doe",
        "Request bounded context for a case",
    ],
)

AGENT_CARD = AgentCard(
    name="AML 314(b) Requestor",
    id="aml-314b-requestor",
    description="FI-A requestor agent for AML 314(b) bilateral communication.",
    url=f"http://{AML314B_REQUESTOR_HOST}:{AML314B_REQUESTOR_PORT}/",
    version="1.0.0",
    defaultInputModes=["text"],
    defaultOutputModes=["text"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[AGENT_SKILL],
    supportsAuthenticatedExtendedCard=False,
)
