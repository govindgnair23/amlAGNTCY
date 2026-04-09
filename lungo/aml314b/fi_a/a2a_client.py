from __future__ import annotations

import json
import logging
from uuid import uuid4

from a2a.types import Message, MessageSendParams, Part, Role, SendMessageRequest, TextPart
from agntcy_app_sdk.factory import AgntcyFactory
from agntcy_app_sdk.semantic.a2a.protocol import A2AProtocol

from aml314b.common.channeling import build_lane_scoped_topic
from aml314b.common.schemas import (
    CollaborationContribution,
    CollaborationSessionRequest,
    DiscoveryRequest,
    DiscoveryResponse,
)
from aml314b.common.stores import DirectoryRoute
from aml314b.fi_a.graph import shared
from aml314b.institutions.fi_b.card import AGENT_CARD as FI_B_CARD
from aml314b.institutions.fi_c.card import AGENT_CARD as FI_C_CARD
from aml314b.institutions.fi_d.card import AGENT_CARD as FI_D_CARD
from aml314b.institutions.fi_e.card import AGENT_CARD as FI_E_CARD
from aml314b.institutions.fi_f.card import AGENT_CARD as FI_F_CARD

logger = logging.getLogger("lungo.aml314b.fi_a.a2a_client")

INSTITUTION_CARDS = {
    "FI_B": FI_B_CARD,
    "FI_C": FI_C_CARD,
    "FI_D": FI_D_CARD,
    "FI_E": FI_E_CARD,
    "FI_F": FI_F_CARD,
}


class DiscoveryA2AClient:
    def __init__(self, *, transport_name: str, sender_name: str = "default/default/fi_a") -> None:
        self.transport_name = transport_name
        self.sender_name = sender_name
        self.factory: AgntcyFactory = shared.get_factory()

    async def send_request(self, request: DiscoveryRequest, route: DirectoryRoute) -> DiscoveryResponse:
        card = INSTITUTION_CARDS[request.target_institution_id]
        if self.transport_name == "A2A":
            client = await self.factory.create_client("A2A", agent_url=route.endpoint or card.url)
        else:
            base_topic = A2AProtocol.create_agent_topic(card)
            transport = self.factory.create_transport(
                self.transport_name,
                endpoint=route.endpoint,
                name=self.sender_name,
            )
            client = await self.factory.create_client(
                "A2A",
                agent_topic=build_lane_scoped_topic(base_topic, request.investigation_type),
                transport=transport,
            )
        payload = json.dumps(request.model_dump(mode="json"))
        send_request = SendMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(
                message=Message(
                    message_id=str(uuid4()),
                    role=Role.user,
                    parts=[Part(TextPart(text=payload))],
                )
            ),
        )
        response = await client.send_message(send_request)
        if hasattr(response.root, "result") and response.root.result and response.root.result.parts:
            part = response.root.result.parts[0].root
            if hasattr(part, "text"):
                return DiscoveryResponse.model_validate(json.loads(part.text))
        if hasattr(response.root, "error") and response.root.error:
            raise ValueError(f"A2A error: {response.root.error.message}")
        raise ValueError("A2A response missing content")


class CollaborationA2AClient:
    def __init__(self, *, transport_name: str, sender_name: str = "default/default/fi_a") -> None:
        self.transport_name = transport_name
        self.sender_name = sender_name
        self.factory: AgntcyFactory = shared.get_factory()

    async def send_request(
        self, request: CollaborationSessionRequest, route: DirectoryRoute
    ) -> CollaborationContribution:
        card = INSTITUTION_CARDS[route.institution_id]
        if self.transport_name == "A2A":
            client = await self.factory.create_client("A2A", agent_url=route.endpoint or card.url)
        else:
            base_topic = A2AProtocol.create_agent_topic(card)
            transport = self.factory.create_transport(
                self.transport_name,
                endpoint=route.endpoint,
                name=self.sender_name,
            )
            client = await self.factory.create_client(
                "A2A",
                agent_topic=build_lane_scoped_topic(base_topic, request.investigation_type),
                transport=transport,
            )
        payload = json.dumps(request.model_dump(mode="json"))
        send_request = SendMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(
                message=Message(
                    message_id=str(uuid4()),
                    role=Role.user,
                    parts=[Part(TextPart(text=payload))],
                )
            ),
        )
        response = await client.send_message(send_request)
        if hasattr(response.root, "result") and response.root.result and response.root.result.parts:
            part = response.root.result.parts[0].root
            if hasattr(part, "text"):
                return CollaborationContribution.model_validate(json.loads(part.text))
        if hasattr(response.root, "error") and response.root.error:
            raise ValueError(f"A2A error: {response.root.error.message}")
        raise ValueError("A2A response missing content")
