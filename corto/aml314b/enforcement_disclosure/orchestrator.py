from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging

from aml314b.schemas import B314Response
from aml314b.stores import DisclosureAuditStore
from aml314b.enforcement_disclosure.layer_cumulative import CumulativeDisclosureLayer
from aml314b.enforcement_disclosure.layer_deterministic import DeterministicPolicyLayer
from aml314b.enforcement_disclosure.layer_semantic import SingleTurnSemanticLayer
from aml314b.enforcement_disclosure.types import (
    DisclosureContext,
    DisclosureDecision,
    LayerDecision,
)

logger = logging.getLogger("corto.aml314b.enforcement_disclosure.orchestrator")


@dataclass
class LayeredDisclosureEnforcer:
    deterministic_layer: DeterministicPolicyLayer
    semantic_layer: SingleTurnSemanticLayer
    cumulative_layer: CumulativeDisclosureLayer
    audit_store: DisclosureAuditStore

    def review_outbound_response(
        self,
        *,
        context: DisclosureContext,
        response: B314Response,
    ) -> DisclosureDecision:
        layer_decisions: list[LayerDecision] = []

        deterministic = self.deterministic_layer.review(context=context, response=response)
        layer_decisions.append(deterministic)
        if not deterministic.allowed:
            return DisclosureDecision.create(
                allowed=False,
                blocked_layer=deterministic.layer,
                layer_decisions=layer_decisions,
            )

        semantic = self.semantic_layer.review(context=context, response=response)
        layer_decisions.append(semantic)
        if not semantic.allowed:
            return DisclosureDecision.create(
                allowed=False,
                blocked_layer=semantic.layer,
                layer_decisions=layer_decisions,
            )

        cumulative = self.cumulative_layer.review(context=context, response=response)
        layer_decisions.append(cumulative)
        if not cumulative.allowed:
            return DisclosureDecision.create(
                allowed=False,
                blocked_layer=cumulative.layer,
                layer_decisions=layer_decisions,
            )

        return DisclosureDecision.create(
            allowed=True,
            blocked_layer=None,
            layer_decisions=layer_decisions,
        )

    def enforce_outbound_response(
        self,
        *,
        context: DisclosureContext,
        response: B314Response,
    ) -> B314Response:
        decision = self.review_outbound_response(context=context, response=response)
        self._record_audit(context=context, response=response, decision=decision)

        if not decision.allowed:
            blocked_layer = decision.blocked_layer or "unknown"
            reason = "; ".join(decision.reasons) or "policy_violation"
            raise ValueError(
                f"Message blocked by layered disclosure enforcement ({blocked_layer}): {reason}"
            )

        return response

    def _record_audit(
        self,
        *,
        context: DisclosureContext,
        response: B314Response,
        decision: DisclosureDecision,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        entities = [entity.strip() for entity in context.entity_ids if entity.strip()]
        if not entities:
            entities = ["UNKNOWN_ENTITY"]

        layer_decisions_json = json.dumps(
            [
                {
                    "layer": layer_decision.layer,
                    "allowed": layer_decision.allowed,
                    "violations": [
                        {
                            "policy_id": violation.policy_id,
                            "reason": violation.reason,
                        }
                        for violation in layer_decision.violations
                    ],
                    "metadata": layer_decision.metadata,
                }
                for layer_decision in decision.layer_decisions
            ]
        )

        reasons = "; ".join(decision.reasons)
        for entity_id in entities:
            self.audit_store.append_review(
                review_id=decision.review_id,
                case_id=context.case_id,
                requester_institution=context.requester_institution,
                responder_institution=context.responder_institution,
                entity_id=entity_id,
                request_message_id=context.request_message_id,
                response_message_id=response.message_id,
                in_reply_to=response.in_reply_to,
                match_type=response.match_type,
                summary=response.summary,
                allowed=decision.allowed,
                blocked_layer=decision.blocked_layer,
                reasons=reasons,
                layer_decisions_json=layer_decisions_json,
                reviewed_at=now,
                sent=decision.allowed,
            )

        logger.info(
            "layered_disclosure review_id=%s case_id=%s allowed=%s blocked_layer=%s",
            decision.review_id,
            context.case_id,
            decision.allowed,
            decision.blocked_layer,
        )
