from __future__ import annotations

from pathlib import Path

import pytest

from aml314b.bilateral import run_bilateral_demo
from config.config import (
    AML314B_ACTIVE_INVESTIGATIONS_PATH,
    AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
    AML314B_CURATED_CONTEXT_PATH,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_bilateral_aml314b_autoprocess_active_cases(tmp_path: Path) -> None:
    retrieved_path = tmp_path / "retrieved_information.csv"

    outcome = await run_bilateral_demo(
        case_id="CASE-JOHN-01",
        retrieved_information_path=str(retrieved_path),
        active_investigations_path=AML314B_ACTIVE_INVESTIGATIONS_PATH,
        known_high_risk_entities_path=AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
        curated_context_path=AML314B_CURATED_CONTEXT_PATH,
    )

    assert outcome["cases_processed"] == 1
    result = outcome["results"][0]
    assert result["case_id"] == "CASE-JOHN-01"
    assert result["status"] == "success"
    assert result["match_type"] == "CONFIRMED_MATCH"

    requestor_directions = {event["direction"] for event in outcome["requestor_enforcement_events"]}
    responder_directions = {event["direction"] for event in outcome["responder_enforcement_events"]}
    assert {"outbound_request", "inbound_response"}.issubset(requestor_directions)
    assert {"inbound_request", "outbound_response"}.issubset(responder_directions)

    assert retrieved_path.exists()
    rows = outcome["retrieved_information_rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["case_id"] == "CASE-JOHN-01"
    assert row["source_institution"] == "FI-B"
    assert row["usage_purpose"] == "AML_314B"
