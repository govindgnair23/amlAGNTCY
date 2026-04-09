from __future__ import annotations

import logging
from typing import Iterable

import httpx

from aml314b.schemas import B314Request, B314Response
from aml314b.step_events import StepEventPayload
from aml314b.stores import ActiveCase, RetrievedInformationStore
from fi_a.responder_types import ResponderResult

logger = logging.getLogger("corto.aml314b.fi_a.tools")

TOOLS = [
    {
        "name": "read_active_investigations",
        "description": "Read all ACTIVE cases from FI-A's ActiveInvestigationsStore.",
    },
    {
        "name": "send_314b_request",
        "description": "Send a validated 314(b) request to FI-B over HTTP.",
    },
    {
        "name": "persist_retrieved_information",
        "description": "Persist an inbound 314(b) response with provenance metadata.",
    },
]


def build_request_from_case(case: ActiveCase) -> B314Request:
    return B314Request(
        case_id=case.case_id,
        entities=[case.entity_id],
        time_window=case.to_time_window(),
        activity_summary=case.activity_summary,
    )


async def send_314b_request(
    client: httpx.AsyncClient,
    request: B314Request,
) -> ResponderResult:
    logger.info(
        "FI-A sending request case_id=%s message_id=%s to %s",
        request.case_id,
        request.message_id,
        client.base_url,
    )
    response = await client.post("/aml314b/request", json=request.model_dump(mode="json"))
    if response.status_code == 400:
        detail = response.json().get("detail", "Request blocked by responder enforcement")
        raise ValueError(detail)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Responder payload must be a JSON object")
    step_events = [
        StepEventPayload.from_dict(event) for event in payload.pop("step_events", [])
    ]
    return ResponderResult(
        response=B314Response.model_validate(payload),
        step_events=step_events,
    )


def persist_retrieved_information(
    retrieved_store: RetrievedInformationStore,
    request: B314Request,
    response: B314Response,
    source_institution: str,
) -> None:
    retrieved_store.append_response(request, response, source_institution=source_institution)
    logger.info(
        "FI-A persisted response case_id=%s response_message_id=%s",
        request.case_id,
        response.message_id,
    )


def select_cases(cases: Iterable[ActiveCase], limit: int | None = None) -> list[ActiveCase]:
    selected = list(cases)
    if limit is not None:
        return selected[:limit]
    return selected
