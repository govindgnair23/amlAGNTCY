from __future__ import annotations

import logging
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from aml314b.enforcement import PlaceholderEnforcementLayer
from aml314b.stores import (
    ActiveInvestigationsStore,
    RetrievedInformationStore,
    CounterpartyDirectoryStore,
)
from config.config import (
    AML314B_REQUESTOR_HOST,
    AML314B_REQUESTOR_PORT,
    AML314B_ACTIVE_INVESTIGATIONS_PATH,
    AML314B_DIRECTORY_PATH,
    AML314B_RETRIEVED_INFORMATION_PATH,
    AML314B_REQUESTOR_AUTOSTART,
    AML314B_REQUESTOR_CASE_LIMIT,
    AML314B_MESSAGE_TRANSPORT,
    AML314B_UI_STEP_DELAY_SECONDS,
)
from config.logging_config import setup_logging
from fi_a.agent import RequestorAgent, CaseExchangeResult
from fi_a.a2a_client import A2AResponderClient
from fi_a.log_buffer import LogBuffer, LogBufferHandler
from aml314b.step_events import StepEventBuffer

load_dotenv()
setup_logging()
logger = logging.getLogger("corto.aml314b.fi_a.main")

app = FastAPI(title="FI-A Requestor Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _serialize_result(result: CaseExchangeResult) -> dict[str, Any]:
    return result.to_dict()


@app.on_event("startup")
async def startup_event() -> None:
    enforcement = PlaceholderEnforcementLayer(logger_name="corto.aml314b.fi_a.enforcement")
    active_store = ActiveInvestigationsStore(AML314B_ACTIVE_INVESTIGATIONS_PATH)
    directory_store = CounterpartyDirectoryStore(AML314B_DIRECTORY_PATH)
    retrieved_store = RetrievedInformationStore(AML314B_RETRIEVED_INFORMATION_PATH)
    log_buffer = LogBuffer(max_entries=500)
    step_buffer = StepEventBuffer(max_entries=500)
    log_handler = LogBufferHandler(log_buffer, logger_prefix="corto.aml314b")
    log_handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(log_handler)
    a2a_client = A2AResponderClient(
        transport_name=AML314B_MESSAGE_TRANSPORT,
    )
    agent = RequestorAgent(
        active_store=active_store,
        retrieved_store=retrieved_store,
        directory_store=directory_store,
        enforcement=enforcement,
        send_request=a2a_client.send_request,
        transport_name=AML314B_MESSAGE_TRANSPORT,
        step_delay_seconds=AML314B_UI_STEP_DELAY_SECONDS,
        step_buffer=step_buffer,
    )

    app.state.enforcement = enforcement
    app.state.active_store = active_store
    app.state.retrieved_store = retrieved_store
    app.state.directory_store = directory_store
    app.state.a2a_client = a2a_client
    app.state.agent = agent
    app.state.log_buffer = log_buffer
    app.state.log_handler = log_handler
    app.state.step_buffer = step_buffer

    if AML314B_REQUESTOR_AUTOSTART:
        try:
            results = await agent.run_active_cases(limit=AML314B_REQUESTOR_CASE_LIMIT)
            logger.info("FI-A autostart completed cases=%s", len(results))
        except Exception as exc:  # pragma: no cover - defensive guard for local startup ordering
            logger.exception("FI-A autostart failed: %s", exc)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    log_handler = getattr(app.state, "log_handler", None)
    if log_handler is not None:
        logging.getLogger().removeHandler(log_handler)
    return None


@app.post("/aml314b/run")
async def run_all_active_cases() -> list[dict[str, Any]]:
    agent: RequestorAgent = app.state.agent
    try:
        results = await agent.run_active_cases(limit=AML314B_REQUESTOR_CASE_LIMIT)
        return [_serialize_result(result) for result in results]
    except ValueError as exc:
        logger.exception("FI-A blocked outbound request: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("FI-A transport error: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach FI-B responder") from exc


@app.post("/aml314b/run/{case_id}")
async def run_single_case(case_id: str) -> dict[str, Any]:
    agent: RequestorAgent = app.state.agent
    try:
        result = await agent.run_case(case_id)
        return _serialize_result(result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        logger.exception("FI-A blocked outbound request: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("FI-A transport error: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach FI-B responder") from exc


@app.get("/aml314b/retrieved")
async def get_retrieved_information() -> list[dict[str, Any]]:
    retrieved_store: RetrievedInformationStore = app.state.retrieved_store
    df = retrieved_store.read_all()
    return df.to_dict(orient="records")


@app.get("/aml314b/logs")
async def get_logs(since_id: int | None = Query(default=None, ge=0)) -> list[dict[str, Any]]:
    log_buffer: LogBuffer = app.state.log_buffer
    return log_buffer.get_since(since_id=since_id)


@app.get("/aml314b/steps")
async def get_steps(
    since_id: int | None = Query(default=None, ge=0),
    case_id: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    step_buffer: StepEventBuffer = app.state.step_buffer
    return step_buffer.get_since(since_id=since_id, case_id=case_id)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "institution": "FI-A"}


if __name__ == "__main__":
    uvicorn.run("fi_a.main:app", host=AML314B_REQUESTOR_HOST, port=AML314B_REQUESTOR_PORT)
