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
async def test_bilateral_phase1b_scenarios(tmp_path: Path) -> None:
    retrieved_path = tmp_path / "retrieved_information.csv"
    internal_path = tmp_path / "internal_investigations.csv"

    outcome = await run_bilateral_demo(
        retrieved_information_path=str(retrieved_path),
        internal_investigations_path=str(internal_path),
        active_investigations_path=AML314B_ACTIVE_INVESTIGATIONS_PATH,
        known_high_risk_entities_path=AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
        curated_context_path=AML314B_CURATED_CONTEXT_PATH,
    )

    assert outcome["cases_processed"] == 5

    results = {result["case_id"]: result for result in outcome["results"]}

    john = results["CASE-JOHN-01"]
    assert john["status"] == "success"
    assert john["match_type"] == "CONFIRMED_MATCH"
    assert "FI-C" in (john["summary"] or "")
    assert "FI-D" in (john["summary"] or "")

    john_ssn = results["CASE-JOHN-SSN"]
    assert john_ssn["status"] == "blocked"
    assert "SSN" in (john_ssn["error_message"] or "")

    jane = results["CASE-JANE-01"]
    assert jane["status"] == "success"
    assert jane["match_type"] == "NO_MATCH"

    jim = results["CASE-JIM-01"]
    assert jim["status"] == "success"
    assert jim["match_type"] == "POTENTIAL_MATCH"
    assert "outside the requested time window" in (jim["summary"] or "").lower()

    jimmy = results["CASE-JIMMY-01"]
    assert jimmy["status"] == "success"
    assert jimmy["match_type"] == "NO_MATCH"
    assert "internal investigation" in (jimmy["summary"] or "").lower()

    retrieved_rows = outcome["retrieved_information_rows"]
    retrieved_case_ids = {row["case_id"] for row in retrieved_rows}
    assert "CASE-JOHN-01" in retrieved_case_ids
    assert "CASE-JANE-01" in retrieved_case_ids
    assert "CASE-JIM-01" in retrieved_case_ids
    assert "CASE-JIMMY-01" in retrieved_case_ids
    assert "CASE-JOHN-SSN" not in retrieved_case_ids

    internal_rows = outcome["internal_investigations_rows"]
    internal_case_ids = {row["case_id"] for row in internal_rows}
    assert "CASE-JIMMY-01" in internal_case_ids
