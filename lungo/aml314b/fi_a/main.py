from __future__ import annotations

import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal
from typing import Any

if __package__ in {None, ""}:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").exists():
            sys.path.insert(0, str(candidate))
            break

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from agntcy_app_sdk.factory import AgntcyFactory
from ioa_observe.sdk.tracing import session_start

from aml314b.common.channeling import normalize_investigation_type
from aml314b.common.probing import LaneProbeResult
from aml314b.common.schemas import CollaborationSessionResult, DiscoveryAggregateResult
from aml314b.common.stores import ActiveCase, ActiveInvestigationsStore
from aml314b.fi_a.graph.graph import AMLDiscoveryGraph, AMLGroupCollaborationGraph
from aml314b.fi_a.graph import shared
from aml314b.fi_a.graph.tools import (
    STEP_BUFFER,
    format_collaboration_summary,
    format_discovery_summary,
    get_step_events,
    probe_investigation_lane,
    run_case_discovery,
    run_case_discovery_and_collaboration,
)
from config.config import (
    AML314B_ACTIVE_INVESTIGATIONS_PATH,
    AML314B_DISCOVERY_REQUESTOR_HOST,
    AML314B_DISCOVERY_REQUESTOR_PORT,
    AML314B_MESSAGE_TRANSPORT,
)
from config.logging_config import setup_logging

load_dotenv()
setup_logging()
shared.set_factory(AgntcyFactory("lungo.aml314b.fi_a", enable_tracing=True))


class PromptRequest(BaseModel):
    prompt: str
    investigation_type: str | None = None


class ProbeRequest(BaseModel):
    investigation_type: str


class CaseRunRequest(BaseModel):
    case_id: str
    investigation_type: str
    run_mode: Literal["discovery", "collaboration"]
    candidate_institutions: list[str] | None = None


LaneProbeRunner = Callable[[str], Awaitable[LaneProbeResult]]
StructuredDiscoveryRunner = Callable[
    [str, str, list[str] | None],
    Awaitable[DiscoveryAggregateResult],
]
StructuredCollaborationRunner = Callable[
    [str, str, list[str] | None],
    Awaitable[tuple[DiscoveryAggregateResult, CollaborationSessionResult]],
]


def _build_observability_payload(metadata: dict[str, Any] | None) -> dict[str, str | None]:
    metadata = metadata or {}
    session_id = metadata.get("executionID")
    traceparent_id = metadata.get("traceparentID")
    return {
        "session_id": str(session_id) if session_id else None,
        "traceparent_id": str(traceparent_id) if traceparent_id else None,
    }


def _serialize_active_case(case: ActiveCase) -> dict[str, str]:
    return {
        "case_id": case.case_id,
        "investigation_type": case.investigation_type.value,
        "entity_id": case.entity_id,
        "entity_name": case.entity_name,
        "counterparty_id": case.counterparty_id,
        "time_window_start": case.time_window_start.isoformat(),
        "time_window_end": case.time_window_end.isoformat(),
        "status": case.status,
        "case_summary": case.activity_summary or "",
    }


def _normalize_prompt_entry(
    entry: object,
    *,
    default_description: str,
) -> dict[str, str]:
    if isinstance(entry, str):
        prompt = entry.strip()
        description = default_description
        investigation_type = None
    elif isinstance(entry, dict):
        prompt = str(entry.get("prompt", "")).strip()
        description = str(entry.get("description", default_description)).strip()
        investigation_type = entry.get("investigation_type")
    else:
        raise ValueError("Suggested prompt entries must be strings or objects.")

    if not prompt:
        raise ValueError("Suggested prompt entry must include a non-empty prompt.")
    if not description:
        description = default_description
    payload = {"prompt": prompt, "description": description}
    if investigation_type is not None:
        payload["investigation_type"] = normalize_investigation_type(
            str(investigation_type)
        ).value
    return payload


def _normalize_prompt_list(
    entries: list[object],
    *,
    default_description: str,
) -> list[dict[str, str]]:
    return [
        _normalize_prompt_entry(entry, default_description=default_description)
        for entry in entries
    ]


def create_app(
    graph: AMLDiscoveryGraph | None = None,
    collaboration_graph: AMLGroupCollaborationGraph | None = None,
    lane_probe_runner: LaneProbeRunner | None = None,
    structured_discovery_runner: StructuredDiscoveryRunner | None = None,
    structured_collaboration_runner: StructuredCollaborationRunner | None = None,
    active_investigations_path: str = AML314B_ACTIVE_INVESTIGATIONS_PATH,
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    discovery_graph = graph or AMLDiscoveryGraph()
    collaboration_graph = collaboration_graph or AMLGroupCollaborationGraph()
    active_store = ActiveInvestigationsStore(active_investigations_path)

    async def _default_lane_probe_runner(investigation_type: str) -> LaneProbeResult:
        return await probe_investigation_lane(investigation_type)

    async def _default_structured_discovery_runner(
        investigation_type: str,
        case_id: str,
        candidate_institutions: list[str] | None,
    ) -> DiscoveryAggregateResult:
        return await run_case_discovery(
            investigation_type,
            case_id,
            candidate_institutions=candidate_institutions,
            active_investigations_path=active_investigations_path,
        )

    async def _default_structured_collaboration_runner(
        investigation_type: str,
        case_id: str,
        candidate_institutions: list[str] | None,
    ) -> tuple[DiscoveryAggregateResult, CollaborationSessionResult]:
        return await run_case_discovery_and_collaboration(
            investigation_type,
            case_id,
            candidate_institutions=candidate_institutions,
            active_investigations_path=active_investigations_path,
        )

    lane_probe_runner = lane_probe_runner or _default_lane_probe_runner
    structured_discovery_runner = (
        structured_discovery_runner or _default_structured_discovery_runner
    )
    structured_collaboration_runner = (
        structured_collaboration_runner or _default_structured_collaboration_runner
    )

    @app.post("/agent/prompt")
    async def handle_prompt(request: PromptRequest):
        try:
            with session_start() as observability_metadata:
                start_event_id = STEP_BUFFER.latest_id()
                result = await discovery_graph.serve(
                    request.prompt,
                    investigation_type=request.investigation_type,
                )
            return {
                "response": result["text"],
                "aggregate_result": result["aggregate_result"],
                "step_events": get_step_events(
                    case_id=result["aggregate_result"]["case_id"],
                    since_id=start_event_id,
                    investigation_type=result["aggregate_result"]["investigation_type"],
                    transport_lane=result["aggregate_result"].get("transport_lane"),
                ),
                "observability": _build_observability_payload(observability_metadata),
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Operation failed: {exc}") from exc

    @app.post("/agent/probe")
    async def handle_probe(request: ProbeRequest):
        try:
            result = await lane_probe_runner(
                normalize_investigation_type(request.investigation_type).value
            )
            return {"probe_result": result.model_dump(mode="json")}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Operation failed: {exc}") from exc

    @app.get("/agent/cases")
    async def list_cases(investigation_type: str = Query(...)):
        try:
            normalized = normalize_investigation_type(investigation_type)
            cases = active_store.list_active_cases(normalized)
            return {"cases": [_serialize_active_case(case) for case in cases]}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/agent/cases/run")
    async def run_case(request: CaseRunRequest):
        try:
            normalized_investigation_type = normalize_investigation_type(
                request.investigation_type
            ).value
            with session_start() as observability_metadata:
                start_event_id = STEP_BUFFER.latest_id()
                if request.run_mode == "collaboration":
                    discovery_result, collaboration_result = (
                        await structured_collaboration_runner(
                            normalized_investigation_type,
                            request.case_id,
                            request.candidate_institutions,
                        )
                    )
                    return {
                        "run_mode": request.run_mode,
                        "response": format_collaboration_summary(collaboration_result),
                        "discovery_result": discovery_result.model_dump(mode="json"),
                        "collaboration_result": collaboration_result.model_dump(mode="json"),
                        "step_events": get_step_events(
                            case_id=discovery_result.case_id,
                            since_id=start_event_id,
                            investigation_type=discovery_result.investigation_type.value,
                            transport_lane=discovery_result.transport_lane,
                        ),
                        "observability": _build_observability_payload(
                            observability_metadata
                        ),
                    }
                discovery_result = await structured_discovery_runner(
                    normalized_investigation_type,
                    request.case_id,
                    request.candidate_institutions,
                )
                return {
                    "run_mode": request.run_mode,
                    "response": format_discovery_summary(discovery_result),
                    "aggregate_result": discovery_result.model_dump(mode="json"),
                    "step_events": get_step_events(
                        case_id=discovery_result.case_id,
                        since_id=start_event_id,
                        investigation_type=discovery_result.investigation_type.value,
                        transport_lane=discovery_result.transport_lane,
                    ),
                    "observability": _build_observability_payload(
                        observability_metadata
                    ),
                }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Operation failed: {exc}") from exc

    @app.post("/agent/prompt/collaboration")
    async def handle_collaboration_prompt(request: PromptRequest):
        try:
            with session_start() as observability_metadata:
                start_event_id = STEP_BUFFER.latest_id()
                result = await collaboration_graph.serve(
                    request.prompt,
                    investigation_type=request.investigation_type,
                )
            return {
                "response": result["text"],
                "discovery_result": result["discovery_result"],
                "collaboration_result": result["collaboration_result"],
                "step_events": get_step_events(
                    case_id=result["discovery_result"]["case_id"],
                    since_id=start_event_id,
                    investigation_type=result["discovery_result"]["investigation_type"],
                    transport_lane=result["discovery_result"].get("transport_lane"),
                ),
                "observability": _build_observability_payload(observability_metadata),
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Operation failed: {exc}") from exc

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    @app.get("/v1/health")
    async def connectivity_health():
        return {"status": "alive", "transport": AML314B_MESSAGE_TRANSPORT}

    @app.get("/agent/step-events")
    async def list_step_events(
        case_id: str = Query(...),
        since_id: int | None = Query(default=None),
        investigation_type: str | None = Query(default=None),
        transport_lane: str | None = Query(default=None),
    ):
        normalized_investigation_type = (
            normalize_investigation_type(investigation_type).value
            if investigation_type is not None
            else None
        )
        return {
            "events": get_step_events(
                case_id=case_id,
                since_id=since_id,
                investigation_type=normalized_investigation_type,
                transport_lane=transport_lane,
            )
        }

    @app.get("/suggested-prompts")
    async def get_prompts():
        prompts_path = Path(__file__).resolve().parent / "suggested_prompts.json"
        data = json.loads(prompts_path.read_text(encoding="utf-8"))
        return {
            "aml_discovery": _normalize_prompt_list(
                data.get("aml_discovery_prompts", []),
                default_description=(
                    "Seeded John Doe discovery case that broadcasts to FI_B through FI_F."
                ),
            ),
            "aml_group_collaboration": _normalize_prompt_list(
                data.get("aml_group_collaboration_prompts", []),
                default_description=(
                    "Seeded John Doe discovery plus collaboration case with the accepting cohort."
                ),
            ),
        }

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "aml314b.fi_a.main:app",
        host=AML314B_DISCOVERY_REQUESTOR_HOST,
        port=AML314B_DISCOVERY_REQUESTOR_PORT,
        reload=True,
    )
