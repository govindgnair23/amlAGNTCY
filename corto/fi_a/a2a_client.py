from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from agntcy_app_sdk.factory import AgntcyFactory
from agntcy_app_sdk.semantic.a2a.protocol import A2AProtocol
from a2a.types import (
    Message,
    MessageSendParams,
    Part,
    Role,
    SendMessageRequest,
    TextPart,
)

from aml314b.schemas import B314Request, B314Response
from aml314b.step_events import StepEventPayload
from aml314b.stores import DirectoryRoute
from config.config import AML314B_ENABLE_TRACING
from fi_a.responder_types import ResponderResult
from fi_b.card import AGENT_CARD as FI_B_CARD

logger = logging.getLogger("corto.aml314b.fi_a.a2a_client")


class A2AResponderClient:
    def __init__(
        self,
        *,
        transport_name: str,
        sender_name: str = "default/default/fi_a",
        enable_tracing: bool = AML314B_ENABLE_TRACING,
    ) -> None:
        self.transport_name = transport_name
        self.sender_name = sender_name
        self.factory = AgntcyFactory("corto.aml.fi_a", enable_tracing=enable_tracing)

    async def send_request(self, request: B314Request, route: DirectoryRoute) -> ResponderResult:
        if self.transport_name == "A2A":
            client = await self.factory.create_client(
                "A2A",
                agent_url=route.endpoint or FI_B_CARD.url,
            )
        else:
            a2a_topic = A2AProtocol.create_agent_topic(FI_B_CARD)
            transport = self.factory.create_transport(
                self.transport_name,
                endpoint=route.endpoint,
                name=self.sender_name,
            )
            client = await self.factory.create_client(
                "A2A",
                agent_topic=a2a_topic,
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
        if hasattr(response.root, "result") and response.root.result:
            if response.root.result.parts:
                part = response.root.result.parts[0].root
                if hasattr(part, "text"):
                    return _parse_response(part.text)
        if hasattr(response.root, "error") and response.root.error:
            raise ValueError(f"A2A error: {response.root.error.message}")
        raise ValueError("A2A response missing content")


def _parse_response(text: str) -> ResponderResult:
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse A2A response: %s", text)
        raise ValueError("Invalid A2A response payload") from exc
    if not isinstance(data, dict):
        raise ValueError("Invalid A2A response payload")
    step_events = [
        StepEventPayload.from_dict(event) for event in data.pop("step_events", [])
    ]
    return ResponderResult(
        response=B314Response.model_validate(data),
        step_events=step_events,
    )
