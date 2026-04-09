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

from aml314b.schemas import B314Request
from aml314b.step_events import StepEventCollector
from fi_b.agent import ResponderAgent

logger = logging.getLogger("corto.aml314b.fi_b.a2a_executor")


class AMLResponderExecutor(AgentExecutor):
    """A2A executor that parses AML 314(b) requests and returns bounded responses."""

    def __init__(self, responder_agent: ResponderAgent) -> None:
        self.responder_agent = responder_agent

    def _validate_request(self, context: RequestContext) -> JSONRPCResponse | None:
        if not context or not context.message or not context.message.parts:
            logger.error("Invalid request parameters: %s", context)
            return JSONRPCResponse(error=ContentTypeNotSupportedError())
        return None

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Received AML A2A request: %s", context.message)
        validation_error = self._validate_request(context)
        if validation_error:
            await event_queue.enqueue_event(validation_error)
            return

        payload = context.get_user_input()
        if not payload:
            await event_queue.enqueue_event(new_agent_text_message("No AML request payload provided."))
            return

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        try:
            request = B314Request.model_validate(json.loads(payload))
            step_collector = StepEventCollector(case_id=request.case_id)
            response = await self.responder_agent.evaluate_request(
                request, step_collector=step_collector
            )
            response_payload = response.model_dump(mode="json")
            response_payload["step_events"] = step_collector.to_payloads()
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(response_payload))
            )
        except json.JSONDecodeError as exc:
            logger.error("Invalid AML payload: %s", payload)
            await event_queue.enqueue_event(new_agent_text_message("Invalid AML request payload."))
            raise ServerError(error=ContentTypeNotSupportedError()) from exc
        except Exception as exc:
            logger.error("AML executor error: %s", exc)
            raise ServerError(error=InternalError()) from exc

    async def cancel(self, request: RequestContext, event_queue: EventQueue) -> Task | None:
        raise ServerError(error=UnsupportedOperationError())
