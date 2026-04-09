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
async def test_directory_lookup_success(tmp_path: Path) -> None:
    retrieved_path = tmp_path / "retrieved_information.csv"
    directory_path = tmp_path / "counterparty_directory.csv"
    directory_path.write_text(
        "institution_id,transport,endpoint,enabled\n"
        "FI-B,SLIM,http://localhost:46357,true\n",
        encoding="utf-8",
    )

    outcome = await run_bilateral_demo(
        case_id="CASE-JOHN-01",
        directory_path=str(directory_path),
        retrieved_information_path=str(retrieved_path),
        active_investigations_path=AML314B_ACTIVE_INVESTIGATIONS_PATH,
        known_high_risk_entities_path=AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
        curated_context_path=AML314B_CURATED_CONTEXT_PATH,
    )

    assert outcome["cases_processed"] == 1
    result = outcome["results"][0]
    assert result["status"] == "success"
    assert result["match_type"] == "CONFIRMED_MATCH"
    assert outcome["retrieved_information_rows"]


@pytest.mark.anyio
async def test_directory_lookup_missing_route_blocks_case(tmp_path: Path) -> None:
    retrieved_path = tmp_path / "retrieved_information.csv"
    directory_path = tmp_path / "counterparty_directory.csv"
    directory_path.write_text(
        "institution_id,transport,endpoint,enabled\n"
        "FI-C,SLIM,http://localhost:46357,true\n",
        encoding="utf-8",
    )

    outcome = await run_bilateral_demo(
        case_id="CASE-JOHN-01",
        directory_path=str(directory_path),
        retrieved_information_path=str(retrieved_path),
        active_investigations_path=AML314B_ACTIVE_INVESTIGATIONS_PATH,
        known_high_risk_entities_path=AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
        curated_context_path=AML314B_CURATED_CONTEXT_PATH,
    )

    assert outcome["cases_processed"] == 1
    result = outcome["results"][0]
    assert result["status"] == "blocked"
    assert "No directory route found" in (result["error_message"] or "")
    assert outcome["retrieved_information_rows"] == []


@pytest.mark.anyio
async def test_directory_lookup_disabled_route_blocks_case(tmp_path: Path) -> None:
    retrieved_path = tmp_path / "retrieved_information.csv"
    directory_path = tmp_path / "counterparty_directory.csv"
    directory_path.write_text(
        "institution_id,transport,endpoint,enabled\n"
        "FI-B,SLIM,http://localhost:46357,false\n",
        encoding="utf-8",
    )

    outcome = await run_bilateral_demo(
        case_id="CASE-JOHN-01",
        directory_path=str(directory_path),
        retrieved_information_path=str(retrieved_path),
        active_investigations_path=AML314B_ACTIVE_INVESTIGATIONS_PATH,
        known_high_risk_entities_path=AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
        curated_context_path=AML314B_CURATED_CONTEXT_PATH,
    )

    assert outcome["cases_processed"] == 1
    result = outcome["results"][0]
    assert result["status"] == "blocked"
    assert "Directory route is disabled" in (result["error_message"] or "")
    assert outcome["retrieved_information_rows"] == []
