from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

LayerName = Literal["deterministic", "semantic_single_turn", "semantic_cumulative"]


@dataclass(frozen=True)
class PolicyViolation:
    policy_id: str
    reason: str


@dataclass
class LayerDecision:
    layer: LayerName
    allowed: bool
    violations: list[PolicyViolation] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def reasons(self) -> list[str]:
        return [violation.reason for violation in self.violations]


@dataclass(frozen=True)
class DisclosureContext:
    case_id: str
    requester_institution: str
    responder_institution: str
    entity_ids: list[str]
    request_message_id: str


@dataclass
class DisclosureDecision:
    review_id: str
    allowed: bool
    blocked_layer: LayerName | None
    layer_decisions: list[LayerDecision]

    @classmethod
    def create(
        cls,
        *,
        allowed: bool,
        blocked_layer: LayerName | None,
        layer_decisions: list[LayerDecision],
    ) -> "DisclosureDecision":
        return cls(
            review_id=str(uuid4()),
            allowed=allowed,
            blocked_layer=blocked_layer,
            layer_decisions=layer_decisions,
        )

    @property
    def reasons(self) -> list[str]:
        reasons: list[str] = []
        for layer_decision in self.layer_decisions:
            reasons.extend(layer_decision.reasons)
        return reasons
