from __future__ import annotations

from dataclasses import dataclass

from aml314b.schemas import B314Response
from aml314b.enforcement_disclosure.critic import DisclosureCritic
from aml314b.enforcement_disclosure.types import (
    DisclosureContext,
    LayerDecision,
    PolicyViolation,
)


@dataclass(frozen=True)
class SemanticLayerConfig:
    policy_text: str
    fail_closed: bool = True


class SingleTurnSemanticLayer:
    """Single-message semantic policy review using an LLM critic."""

    def __init__(self, *, critic: DisclosureCritic, config: SemanticLayerConfig) -> None:
        self._critic = critic
        self._config = config

    def review(
        self,
        *,
        context: DisclosureContext,
        response: B314Response,
    ) -> LayerDecision:
        try:
            decision = self._critic.review_single_turn(
                policy_text=self._config.policy_text,
                context=context,
                response=response,
            )
        except Exception as exc:
            if self._config.fail_closed:
                return LayerDecision(
                    layer="semantic_single_turn",
                    allowed=False,
                    violations=[
                        PolicyViolation(
                            policy_id="SEMANTIC_SINGLE_TURN_ERROR",
                            reason=f"Single-turn semantic critic failed: {exc}",
                        )
                    ],
                    metadata={"fallback": "fail_closed"},
                )
            return LayerDecision(
                layer="semantic_single_turn",
                allowed=True,
                metadata={"fallback": "fail_open"},
            )

        if decision.allowed:
            return LayerDecision(
                layer="semantic_single_turn",
                allowed=True,
                metadata={
                    "reason_code": decision.reason_code,
                    "rationale": decision.rationale,
                },
            )

        return LayerDecision(
            layer="semantic_single_turn",
            allowed=False,
            violations=[
                PolicyViolation(
                    policy_id=f"SEMANTIC_SINGLE_TURN_{decision.reason_code}",
                    reason=decision.rationale,
                )
            ],
            metadata={
                "reason_code": decision.reason_code,
                "raw": decision.raw_response,
            },
        )
