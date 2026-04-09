from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from aml314b.bilateral import run_bilateral_demo
from aml314b.enforcement_disclosure import (
    CriticDecision,
    CumulativeDisclosureLayer,
    CumulativeLayerConfig,
    DeterministicPolicyLayer,
    DisclosureContext,
    LayeredDisclosureEnforcer,
    SemanticLayerConfig,
    SingleTurnSemanticLayer,
)
from aml314b.schemas import B314Response
from aml314b.stores import DisclosureAuditStore
from config.config import (
    AML314B_ACTIVE_INVESTIGATIONS_PATH,
    AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
    AML314B_CURATED_CONTEXT_PATH,
)


@dataclass
class StubDisclosureCritic:
    block_single_turn: bool = False
    block_cumulative_after_first: bool = False
    likelihood_by_history_count: dict[int, str] = field(default_factory=dict)

    def review_single_turn(self, *, policy_text, context, response):
        del policy_text, context, response
        if self.block_single_turn:
            return CriticDecision(
                allowed=False,
                reason_code="SINGLE_TURN_POLICY",
                rationale="Single-turn semantic policy violation",
                raw_response='{"decision":"BLOCK"}',
            )
        return CriticDecision(
            allowed=True,
            reason_code="OK",
            rationale="Allowed",
            raw_response='{"decision":"ALLOW"}',
        )

    def review_cumulative(
        self,
        *,
        policy_text,
        context,
        entity_id,
        history_summaries,
        response,
    ):
        del policy_text, context, entity_id, response
        history_count = len(history_summaries)
        if self.block_cumulative_after_first and history_count >= 1:
            return CriticDecision(
                allowed=False,
                reason_code="CUMULATIVE_POLICY",
                rationale="Cumulative semantic policy violation",
                raw_response='{"decision":"BLOCK"}',
            )

        likelihood = self.likelihood_by_history_count.get(history_count)
        return CriticDecision(
            allowed=True,
            reason_code="OK",
            rationale="Allowed",
            raw_response='{"decision":"ALLOW"}',
            likelihood=likelihood,
        )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_phase2b_layer1_deterministic_block(tmp_path: Path) -> None:
    outcome = await run_bilateral_demo(
        case_id="CASE-JOHN-SSN",
        retrieved_information_path=str(tmp_path / "retrieved.csv"),
        internal_investigations_path=str(tmp_path / "internal.csv"),
        disclosure_audit_path=str(tmp_path / "disclosure_audit.csv"),
        layered_disclosure_enabled=True,
        disclosure_critic=StubDisclosureCritic(),
        active_investigations_path=AML314B_ACTIVE_INVESTIGATIONS_PATH,
        known_high_risk_entities_path=AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
        curated_context_path=AML314B_CURATED_CONTEXT_PATH,
    )

    result = outcome["results"][0]
    assert result["status"] == "blocked"
    assert "deterministic" in (result["error_message"] or "").lower()
    assert outcome["retrieved_information_rows"] == []

    audit_rows = outcome["disclosure_audit_rows"]
    assert len(audit_rows) == 1
    assert audit_rows[0]["blocked_layer"] == "deterministic"


@pytest.mark.anyio
async def test_phase2b_layer2_semantic_block(tmp_path: Path) -> None:
    outcome = await run_bilateral_demo(
        case_id="CASE-JOHN-01",
        retrieved_information_path=str(tmp_path / "retrieved.csv"),
        internal_investigations_path=str(tmp_path / "internal.csv"),
        disclosure_audit_path=str(tmp_path / "disclosure_audit.csv"),
        layered_disclosure_enabled=True,
        disclosure_critic=StubDisclosureCritic(block_single_turn=True),
        active_investigations_path=AML314B_ACTIVE_INVESTIGATIONS_PATH,
        known_high_risk_entities_path=AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
        curated_context_path=AML314B_CURATED_CONTEXT_PATH,
    )

    result = outcome["results"][0]
    assert result["status"] == "blocked"
    assert "semantic_single_turn" in (result["error_message"] or "")
    assert outcome["retrieved_information_rows"] == []

    audit_rows = outcome["disclosure_audit_rows"]
    assert len(audit_rows) == 1
    assert audit_rows[0]["blocked_layer"] == "semantic_single_turn"


@pytest.mark.anyio
async def test_phase2b_layer3_cumulative_block(tmp_path: Path) -> None:
    disclosure_path = tmp_path / "disclosure_audit.csv"

    first = await run_bilateral_demo(
        case_id="CASE-JOHN-01",
        retrieved_information_path=str(tmp_path / "retrieved_first.csv"),
        internal_investigations_path=str(tmp_path / "internal_first.csv"),
        disclosure_audit_path=str(disclosure_path),
        layered_disclosure_enabled=True,
        disclosure_critic=StubDisclosureCritic(block_cumulative_after_first=True),
        active_investigations_path=AML314B_ACTIVE_INVESTIGATIONS_PATH,
        known_high_risk_entities_path=AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
        curated_context_path=AML314B_CURATED_CONTEXT_PATH,
    )
    assert first["results"][0]["status"] == "success"

    second = await run_bilateral_demo(
        case_id="CASE-JOHN-01",
        retrieved_information_path=str(tmp_path / "retrieved_second.csv"),
        internal_investigations_path=str(tmp_path / "internal_second.csv"),
        disclosure_audit_path=str(disclosure_path),
        layered_disclosure_enabled=True,
        disclosure_critic=StubDisclosureCritic(block_cumulative_after_first=True),
        active_investigations_path=AML314B_ACTIVE_INVESTIGATIONS_PATH,
        known_high_risk_entities_path=AML314B_KNOWN_HIGH_RISK_ENTITIES_PATH,
        curated_context_path=AML314B_CURATED_CONTEXT_PATH,
    )

    result = second["results"][0]
    assert result["status"] == "blocked"
    assert "semantic_cumulative" in (result["error_message"] or "")
    assert second["retrieved_information_rows"] == []

    audit_rows = second["disclosure_audit_rows"]
    assert len(audit_rows) == 2
    assert audit_rows[0]["sent"] in (True, "True", "true", 1)
    assert audit_rows[1]["blocked_layer"] == "semantic_cumulative"


def _build_sequence_enforcer(tmp_path: Path, critic: StubDisclosureCritic) -> LayeredDisclosureEnforcer:
    audit_store = DisclosureAuditStore(tmp_path / "disclosure_audit_sequence.csv")
    return LayeredDisclosureEnforcer(
        deterministic_layer=DeterministicPolicyLayer(),
        semantic_layer=SingleTurnSemanticLayer(
            critic=critic,
            config=SemanticLayerConfig(policy_text="No direct net-worth disclosure", fail_closed=True),
        ),
        cumulative_layer=CumulativeDisclosureLayer(
            critic=critic,
            audit_store=audit_store,
            config=CumulativeLayerConfig(
                policy_text=(
                    "The institution must not disclose customer net worth directly or "
                    "through cumulative inference across requester/entity disclosures."
                ),
                fail_closed=True,
            ),
        ),
        audit_store=audit_store,
    )


def _sequence_context(message_id: str) -> DisclosureContext:
    return DisclosureContext(
        case_id="CASE-HNW-01",
        requester_institution="FI-A",
        responder_institution="FI-B",
        entity_ids=["ENTITY-X"],
        request_message_id=message_id,
    )


def _sequence_response(message_id: str, summary: str) -> B314Response:
    return B314Response(
        in_reply_to=message_id,
        match_type="POTENTIAL_MATCH",
        summary=summary,
    )


@pytest.mark.anyio
async def test_phase2b_cumulative_high_net_worth_inference_block(tmp_path: Path) -> None:
    critic = StubDisclosureCritic(
        likelihood_by_history_count={
            0: "VERY_UNLIKELY",
            1: "UNLIKELY",
            2: "UNLIKELY",
            3: "LIKELY",
        }
    )
    enforcer = _build_sequence_enforcer(tmp_path, critic)

    messages = [
        (
            "MSG-1",
            "FI-B confirms aggregate credits above policy threshold in the last 12 months.",
        ),
        (
            "MSG-2",
            "FI-B confirms Entity X maintains investment or wealth management products.",
        ),
        (
            "MSG-3",
            "FI-B confirms recent real estate settlement transaction activity.",
        ),
        (
            "MSG-4",
            "FI-B confirms Entity X maintains foreign-currency accounts and assets with an international affiliate.",
        ),
    ]

    for message_id, summary in messages[:3]:
        response = enforcer.enforce_outbound_response(
            context=_sequence_context(message_id),
            response=_sequence_response(message_id, summary),
        )
        assert response.summary == summary

    with pytest.raises(ValueError, match="semantic_cumulative") as exc_info:
        enforcer.enforce_outbound_response(
            context=_sequence_context(messages[3][0]),
            response=_sequence_response(messages[3][0], messages[3][1]),
        )

    assert "LIKELY" in str(exc_info.value)

    rows = enforcer.audit_store.read_all().to_dict(orient="records")
    assert len(rows) == 4
    assert [row["sent"] for row in rows[:3]] == [True, True, True]
    assert rows[3]["sent"] in (False, "False", "false", 0)
    assert rows[3]["blocked_layer"] == "semantic_cumulative"
    assert "LIKELY" in (rows[3]["reasons"] or "")
