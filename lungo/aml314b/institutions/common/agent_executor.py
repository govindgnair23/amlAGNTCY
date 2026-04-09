from __future__ import annotations

import json
import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    ContentTypeNotSupportedError,
    InternalError,
    JSONRPCResponse,
    Task,
    UnsupportedOperationError,
)
from a2a.utils import new_agent_text_message, new_task
from a2a.utils.errors import ServerError

from aml314b.common.schemas import DiscoveryRequest
from aml314b.common.schemas import CollaborationSessionRequest
from aml314b.institutions.common.collaboration_agent import InstitutionCollaborationAgent
from aml314b.institutions.common.discovery_agent import InstitutionDiscoveryAgent

logger = logging.getLogger("lungo.aml314b.discovery.executor")


class AMLResponderExecutor(AgentExecutor):
    def __init__(
        self,
        discovery_agent: InstitutionDiscoveryAgent,
        collaboration_agent: InstitutionCollaborationAgent,
        transport_name: str = "A2A",
    ) -> None:
        self.discovery_agent = discovery_agent
        self.collaboration_agent = collaboration_agent
        self.transport_name = transport_name

    def _validate_request(self, context: RequestContext) -> JSONRPCResponse | None:
        if not context or not context.message or not context.message.parts:
            logger.error("Invalid request parameters: %s", context)
            return JSONRPCResponse(error=ContentTypeNotSupportedError())
        return None

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        validation_error = self._validate_request(context)
        if validation_error:
            await event_queue.enqueue_event(validation_error)
            return

        payload = context.get_user_input()
        if not payload:
            await event_queue.enqueue_event(
                new_agent_text_message("No AML payload provided.")
            )
            return

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        try:
            raw_payload = json.loads(payload)
            if "session_id" in raw_payload:
                request = CollaborationSessionRequest.model_validate(raw_payload)
                response = await self.collaboration_agent.contribute(request)
            else:
                request = DiscoveryRequest.model_validate(raw_payload)
                response = await self.discovery_agent.evaluate_request(request)
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(response.model_dump(mode="json")))
            )
        except json.JSONDecodeError as exc:
            logger.error("Invalid AML payload: %s", payload)
            await event_queue.enqueue_event(
                new_agent_text_message("Invalid AML request payload.")
            )
            raise ServerError(error=ContentTypeNotSupportedError()) from exc
        except Exception as exc:
            logger.error("AML responder executor error: %s", exc)
            raise ServerError(error=InternalError()) from exc

    async def cancel(self, request: RequestContext, event_queue: EventQueue) -> Task | None:
        raise ServerError(error=UnsupportedOperationError())
