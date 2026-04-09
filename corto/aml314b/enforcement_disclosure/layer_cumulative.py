from __future__ import annotations

from dataclasses import dataclass

from aml314b.schemas import B314Response
from aml314b.stores import DisclosureAuditStore
from aml314b.enforcement_disclosure.critic import DisclosureCritic
from aml314b.enforcement_disclosure.types import (
    DisclosureContext,
    LayerDecision,
    PolicyViolation,
)


@dataclass(frozen=True)
class CumulativeLayerConfig:
    policy_text: str
    fail_closed: bool = True
    blocked_likelihoods: tuple[str, ...] = ("LIKELY", "VERY_LIKELY")


class CumulativeDisclosureLayer:
    """Cumulative disclosure review by requester+entity history."""

    def __init__(
        self,
        *,
        critic: DisclosureCritic,
        audit_store: DisclosureAuditStore,
        config: CumulativeLayerConfig,
    ) -> None:
        self._critic = critic
        self._audit_store = audit_store
        self._config = config

    def review(
        self,
        *,
        context: DisclosureContext,
        response: B314Response,
    ) -> LayerDecision:
        entity_ids = [entity.strip() for entity in context.entity_ids if entity.strip()]
        if not entity_ids:
            entity_ids = ["UNKNOWN_ENTITY"]

        metadata: dict[str, str] = {
            "entities_evaluated": ",".join(entity_ids)
        }

        for entity_id in entity_ids:
            history_records = self._audit_store.list_sent_history(
                requester_institution=context.requester_institution,
                entity_id=entity_id,
            )
            history_summaries = [record.summary for record in history_records]

            try:
                decision = self._critic.review_cumulative(
                    policy_text=self._config.policy_text,
                    context=context,
                    entity_id=entity_id,
                    history_summaries=history_summaries,
                    response=response,
                )
            except Exception as exc:
                if self._config.fail_closed:
                    return LayerDecision(
                        layer="semantic_cumulative",
                        allowed=False,
                        violations=[
                            PolicyViolation(
                                policy_id="SEMANTIC_CUMULATIVE_ERROR",
                                reason=(
                                    "Cumulative semantic critic failed for "
                                    f"entity {entity_id}: {exc}"
                                ),
                            )
                        ],
                        metadata={
                            "fallback": "fail_closed",
                            "entity_id": entity_id,
                            "history_count": str(len(history_summaries)),
                        },
                    )
                continue

            if decision.likelihood in self._config.blocked_likelihoods:
                return LayerDecision(
                    layer="semantic_cumulative",
                    allowed=False,
                    violations=[
                        PolicyViolation(
                            policy_id="SEMANTIC_CUMULATIVE_HIGH_NET_WORTH_INFERENCE",
                            reason=(
                                "Cumulative disclosure blocked for "
                                f"entity {entity_id}: high-net-worth inference "
                                f"is {decision.likelihood}. {decision.rationale}"
                            ),
                        )
                    ],
                    metadata={
                        "reason_code": decision.reason_code,
                        "entity_id": entity_id,
                        "history_count": str(len(history_summaries)),
                        "likelihood": decision.likelihood,
                        "raw": decision.raw_response,
                    },
                )

            if not decision.allowed:
                return LayerDecision(
                    layer="semantic_cumulative",
                    allowed=False,
                    violations=[
                        PolicyViolation(
                            policy_id=f"SEMANTIC_CUMULATIVE_{decision.reason_code}",
                            reason=(
                                "Cumulative disclosure blocked for "
                                f"entity {entity_id}: {decision.rationale}"
                            ),
                        )
                    ],
                    metadata={
                        "reason_code": decision.reason_code,
                        "entity_id": entity_id,
                        "history_count": str(len(history_summaries)),
                        "likelihood": decision.likelihood or "",
                        "raw": decision.raw_response,
                    },
                )

        return LayerDecision(
            layer="semantic_cumulative",
            allowed=True,
            metadata=metadata,
        )
