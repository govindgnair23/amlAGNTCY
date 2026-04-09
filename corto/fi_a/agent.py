from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from aml314b.enforcement import PlaceholderEnforcementLayer
from aml314b.schemas import B314Request, B314Response
from aml314b.step_events import StepEventBuffer, StepEventPayload
from aml314b.stores import (
    ActiveInvestigationsStore,
    RetrievedInformationStore,
    CounterpartyDirectoryStore,
    DirectoryRoute,
)
from config.config import AML314B_ENABLE_TRACING

from fi_a import tools
from fi_a.responder_types import ResponderResult

logger = logging.getLogger("corto.aml314b.fi_a.agent")

if AML314B_ENABLE_TRACING:
    from ioa_observe.sdk.decorators import agent as observe_agent
else:
    def observe_agent(*_args, **_kwargs):
        def decorator(obj):
            return obj
        return decorator

STEP_SEQUENCE: list[tuple[str, str]] = [
    ("fi_a_preparing_request", "FI-A preparing request"),
    (
        "fi_a_outbound_reviewed",
        "FI-A outbound request reviewed for policy violation",
    ),
    ("fi_a_request_sent", "FI-A request sent"),
    ("fi_b_preparing_response", "FI-B preparing response"),
    ("fi_b_response_reviewed", "FI-B response reviewed for policy violation"),
    ("fi_b_response_sent", "FI-B response sent"),
    ("fi_a_response_received", "FI-A received response"),
]


@dataclass
class CaseExchangeResult:
    status: str
    request: B314Request | None = None
    response: B314Response | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "case_id": self.request.case_id if self.request else None,
            "request_message_id": self.request.message_id if self.request else None,
            "response_message_id": self.response.message_id if self.response else None,
            "match_type": self.response.match_type if self.response else None,
            "summary": self.response.summary if self.response else None,
            "error_message": self.error_message,
        }


@observe_agent(name="fi_a_requestor_agent")
class RequestorAgent:
    """FI-A requestor agent that automatically processes active cases."""

    def __init__(
        self,
        active_store: ActiveInvestigationsStore,
        retrieved_store: RetrievedInformationStore,
        directory_store: CounterpartyDirectoryStore,
        enforcement: PlaceholderEnforcementLayer,
        send_request: Callable[[B314Request, DirectoryRoute], Awaitable[ResponderResult]],
        transport_name: str,
        responder_institution: str = "FI-B",
        step_delay_seconds: float = 0.0,
        step_buffer: StepEventBuffer | None = None,
    ) -> None:
        self.active_store = active_store
        self.retrieved_store = retrieved_store
        self.directory_store = directory_store
        self.enforcement = enforcement
        self.send_request = send_request
        self.transport_name = transport_name
        self.responder_institution = responder_institution
        self.step_delay_seconds = step_delay_seconds
        self.step_buffer = step_buffer

    async def run_active_cases(self, limit: int | None = None) -> list[CaseExchangeResult]:
        cases = tools.select_cases(self.active_store.list_active_cases(), limit=limit)
        logger.info("FI-A processing %s active cases", len(cases))
        results: list[CaseExchangeResult] = []
        for case in cases:
            results.append(await self._process_case(case.case_id))
        return results

    async def run_case(self, case_id: str) -> CaseExchangeResult:
        return await self._process_case(case_id)

    async def _process_case(self, case_id: str) -> CaseExchangeResult:
        case = self.active_store.get_case(case_id)
        emitted_steps: set[str] = set()
        await self._emit_step(
            case_id,
            "fi_a_preparing_request",
            "FI-A preparing request",
            emitted_steps=emitted_steps,
        )
        request = tools.build_request_from_case(case)
        try:
            route = self.directory_store.get_route(
                institution_id=case.counterparty_id,
                transport=self.transport_name,
            )
            enforced_request = self.enforcement.enforce_outbound_request(request)
            await self._emit_step(
                case_id,
                "fi_a_outbound_reviewed",
                "FI-A outbound request reviewed for policy violation",
                emitted_steps=emitted_steps,
            )
            await self._emit_step(
                case_id,
                "fi_a_request_sent",
                "FI-A request sent",
                delay_after=False,
                emitted_steps=emitted_steps,
            )
            responder_result = await self.send_request(enforced_request, route)
            await self._emit_responder_steps(
                case_id, responder_result.step_events, emitted_steps
            )
            enforced_response = self.enforcement.enforce_inbound_response(
                responder_result.response, case_id=enforced_request.case_id
            )
            tools.persist_retrieved_information(
                self.retrieved_store,
                enforced_request,
                enforced_response,
                source_institution=self.responder_institution,
            )
            await self._emit_step(
                case_id,
                "fi_a_response_received",
                "FI-A received response",
                emitted_steps=emitted_steps,
            )
            await self._ensure_step_sequence(case_id, emitted_steps)
            logger.info(
                "FI-A completed case_id=%s match_type=%s",
                enforced_request.case_id,
                enforced_response.match_type,
            )
            return CaseExchangeResult(
                status="success",
                request=enforced_request,
                response=enforced_response,
            )
        except ValueError as exc:
            logger.warning("FI-A blocked case_id=%s: %s", case.case_id, exc)
            return CaseExchangeResult(
                status="blocked",
                request=request,
                error_message=str(exc),
            )
        except httpx.HTTPError as exc:
            logger.exception("FI-A transport failure case_id=%s: %s", case.case_id, exc)
            return CaseExchangeResult(
                status="error",
                request=request,
                error_message="transport_error",
            )

    async def _emit_step(
        self,
        case_id: str,
        step_name: str,
        message: str,
        *,
        delay_after: bool = True,
        emitted_steps: set[str] | None = None,
    ) -> None:
        if self.step_buffer:
            self.step_buffer.append_raw(
                case_id=case_id,
                step_name=step_name,
                message=message,
            )
        if emitted_steps is not None:
            emitted_steps.add(step_name)
        if delay_after:
            await self._maybe_delay(step_name, case_id=case_id)

    async def _emit_external_steps(self, steps: list[StepEventPayload]) -> None:
        for step in steps:
            if self.step_buffer:
                self.step_buffer.append(step)
            await self._maybe_delay(step.step_name, case_id=step.case_id)

    async def _emit_responder_steps(
        self,
        case_id: str,
        steps: list[StepEventPayload],
        emitted_steps: set[str],
    ) -> None:
        step_map = {step.step_name: step for step in steps}
        ordered = [
            ("fi_b_preparing_response", "FI-B preparing response"),
            ("fi_b_response_reviewed", "FI-B response reviewed for policy violation"),
            ("fi_b_response_sent", "FI-B response sent"),
        ]
        for step_name, message in ordered:
            step = step_map.get(step_name)
            if step:
                if self.step_buffer:
                    self.step_buffer.append(step)
                await self._maybe_delay(step.step_name, case_id=step.case_id)
                emitted_steps.add(step_name)
            else:
                await self._emit_step(
                    case_id, step_name, message, emitted_steps=emitted_steps
                )

    async def _ensure_step_sequence(self, case_id: str, emitted_steps: set[str]) -> None:
        missing = [step for step in STEP_SEQUENCE if step[0] not in emitted_steps]
        for step_name, message in missing:
            await self._emit_step(
                case_id,
                step_name,
                message,
                emitted_steps=emitted_steps,
            )

    async def _maybe_delay(self, step: str, *, case_id: str) -> None:
        if self.step_delay_seconds <= 0:
            return
        logger.info(
            "FI-A demo delay step=%s seconds=%s case_id=%s",
            step,
            self.step_delay_seconds,
            case_id,
        )
        await asyncio.sleep(self.step_delay_seconds)
