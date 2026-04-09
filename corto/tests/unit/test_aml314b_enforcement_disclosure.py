from __future__ import annotations

from dataclasses import dataclass, field

import pytest

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


@dataclass
class StubDisclosureCritic:
    block_single_turn: bool = False
    block_cumulative_after_first: bool = False

    def review_single_turn(self, *, policy_text, context, response):
        del policy_text, context, response
        if self.block_single_turn:
            return CriticDecision(
                allowed=False,
                reason_code="SINGLE_TURN_POLICY",
                rationale="Single-turn policy violation",
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
        if self.block_cumulative_after_first and len(history_summaries) >= 1:
            return CriticDecision(
                allowed=False,
                reason_code="CUMULATIVE_POLICY",
                rationale="Cumulative disclosure threshold exceeded",
                raw_response='{"decision":"BLOCK"}',
            )
        return CriticDecision(
            allowed=True,
            reason_code="OK",
            rationale="Allowed",
            raw_response='{"decision":"ALLOW"}',
        )


@dataclass
class LikelihoodSequenceCritic:
    likelihoods: list[str] = field(default_factory=list)
    _calls: int = 0

    def review_single_turn(self, *, policy_text, context, response):
        del policy_text, context, response
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
        del policy_text, context, entity_id, history_summaries, response
        likelihood = self.likelihoods[min(self._calls, len(self.likelihoods) - 1)]
        self._calls += 1
        return CriticDecision(
            allowed=True,
            reason_code="NET_WORTH_INFERENCE",
            rationale="Cumulative disclosures indicate possible high net worth",
            raw_response='{"decision":"ALLOW"}',
            likelihood=likelihood,
        )


def _build_enforcer(tmp_path, critic) -> LayeredDisclosureEnforcer:
    audit_store = DisclosureAuditStore(tmp_path / "disclosure_audit.csv")
    return LayeredDisclosureEnforcer(
        deterministic_layer=DeterministicPolicyLayer(),
        semantic_layer=SingleTurnSemanticLayer(
            critic=critic,
            config=SemanticLayerConfig(policy_text="test policy", fail_closed=True),
        ),
        cumulative_layer=CumulativeDisclosureLayer(
            critic=critic,
            audit_store=audit_store,
            config=CumulativeLayerConfig(policy_text="test policy", fail_closed=True),
        ),
        audit_store=audit_store,
    )


def _context() -> DisclosureContext:
    return DisclosureContext(
        case_id="CASE-UNIT-01",
        requester_institution="FI-A",
        responder_institution="FI-B",
        entity_ids=["ENTITY-1"],
        request_message_id="request-1",
    )


def _response(summary: str, in_reply_to: str = "request-1") -> B314Response:
    return B314Response(
        in_reply_to=in_reply_to,
        match_type="CONFIRMED_MATCH",
        summary=summary,
    )


def test_deterministic_layer_blocks_ssn_like_summary(tmp_path) -> None:
    enforcer = _build_enforcer(tmp_path, StubDisclosureCritic())

    with pytest.raises(ValueError, match="deterministic"):
        enforcer.enforce_outbound_response(
            context=_context(),
            response=_response("Entity data includes SSN 123-45-6789"),
        )


def test_semantic_layer_blocks_when_critic_blocks(tmp_path) -> None:
    enforcer = _build_enforcer(
        tmp_path,
        StubDisclosureCritic(block_single_turn=True),
    )

    with pytest.raises(ValueError, match="semantic_single_turn"):
        enforcer.enforce_outbound_response(
            context=_context(),
            response=_response("Bounded context without direct identifiers"),
        )


def test_cumulative_layer_uses_requester_entity_history(tmp_path) -> None:
    enforcer = _build_enforcer(
        tmp_path,
        StubDisclosureCritic(block_cumulative_after_first=True),
    )

    first_response = enforcer.enforce_outbound_response(
        context=_context(),
        response=_response("First bounded disclosure"),
    )
    assert first_response.summary == "First bounded disclosure"

    with pytest.raises(ValueError, match="semantic_cumulative"):
        enforcer.enforce_outbound_response(
            context=_context(),
            response=_response("Second bounded disclosure"),
        )

    history = enforcer.audit_store.list_sent_history(
        requester_institution="FI-A",
        entity_id="ENTITY-1",
    )
    assert len(history) == 1
    assert history[0].summary == "First bounded disclosure"

    rows = enforcer.audit_store.read_all()
    assert len(rows) == 2


def test_cumulative_likelihood_threshold_blocks_likely_or_higher(tmp_path) -> None:
    enforcer = _build_enforcer(
        tmp_path,
        LikelihoodSequenceCritic(likelihoods=["UNLIKELY", "LIKELY"]),
    )

    first_response = enforcer.enforce_outbound_response(
        context=_context(),
        response=_response("First bounded disclosure"),
    )
    assert first_response.summary == "First bounded disclosure"

    with pytest.raises(ValueError, match="semantic_cumulative"):
        enforcer.enforce_outbound_response(
            context=_context(),
            response=_response("Second bounded disclosure"),
        )
