from __future__ import annotations

from dataclasses import dataclass
import re

from aml314b.schemas import B314Response
from aml314b.enforcement_disclosure.types import (
    DisclosureContext,
    LayerDecision,
    PolicyViolation,
)


DEFAULT_REQUIRED_FIELDS = (
    "message_id",
    "in_reply_to",
    "summary",
    "usage_constraints",
)


@dataclass(frozen=True)
class DeterministicPolicyConfig:
    required_response_fields: tuple[str, ...] = DEFAULT_REQUIRED_FIELDS
    ssn_patterns: tuple[str, ...] = (
        r"\b\d{3}-\d{2}-\d{4}\b",
        r"\b\d{9}\b",
    )


class DeterministicPolicyLayer:
    """Schema and regex checks for outbound responses."""

    def __init__(self, config: DeterministicPolicyConfig | None = None) -> None:
        self._config = config or DeterministicPolicyConfig()
        self._compiled_patterns = tuple(
            re.compile(pattern) for pattern in self._config.ssn_patterns
        )

    def review(
        self,
        *,
        context: DisclosureContext,
        response: B314Response,
    ) -> LayerDecision:
        del context
        violations: list[PolicyViolation] = []
        metadata: dict[str, str] = {
            "required_fields": ",".join(self._config.required_response_fields)
        }

        try:
            validated = B314Response.model_validate(response.model_dump())
        except Exception as exc:
            violations.append(
                PolicyViolation(
                    policy_id="DETERMINISTIC_SCHEMA",
                    reason=f"Response schema validation failed: {exc}",
                )
            )
            return LayerDecision(
                layer="deterministic",
                allowed=False,
                violations=violations,
                metadata=metadata,
            )

        dumped = validated.model_dump()
        for field_name in self._config.required_response_fields:
            value = dumped.get(field_name)
            if value is None:
                violations.append(
                    PolicyViolation(
                        policy_id="DETERMINISTIC_REQUIRED_FIELD",
                        reason=f"Missing required response field: {field_name}",
                    )
                )
                continue
            if isinstance(value, str) and not value.strip():
                violations.append(
                    PolicyViolation(
                        policy_id="DETERMINISTIC_REQUIRED_FIELD",
                        reason=f"Required response field is empty: {field_name}",
                    )
                )

        if validated.usage_constraints.purpose != "AML_314B":
            violations.append(
                PolicyViolation(
                    policy_id="DETERMINISTIC_USAGE_PURPOSE",
                    reason="usage_constraints.purpose must be AML_314B",
                )
            )

        for pattern in self._compiled_patterns:
            if pattern.search(validated.summary):
                violations.append(
                    PolicyViolation(
                        policy_id="DETERMINISTIC_SSN_PATTERN",
                        reason="Response summary contains an SSN-like pattern",
                    )
                )
                break

        return LayerDecision(
            layer="deterministic",
            allowed=not violations,
            violations=violations,
            metadata=metadata,
        )
