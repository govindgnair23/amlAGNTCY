from __future__ import annotations

from dataclasses import dataclass

from aml314b.schemas import B314Response
from aml314b.step_events import StepEventPayload


@dataclass(frozen=True)
class ResponderResult:
    response: B314Response
    step_events: list[StepEventPayload]
