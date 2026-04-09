from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from aml314b.common.channeling import InvestigationType, resolve_investigation_type
from aml314b.common.schemas import CollaborationSessionResult, DiscoveryAggregateResult
from aml314b.fi_a.graph.models import DiscoveryPromptParams
from aml314b.fi_a.graph.tools import (
    broadcast_discovery,
    format_collaboration_summary,
    format_discovery_summary,
    get_step_events,
    run_discovery_and_collaboration,
)

BroadcastFunc = Callable[[InvestigationType, str, str, str, str], Awaitable[DiscoveryAggregateResult]]
CollaborateFunc = Callable[
    [InvestigationType, str, str, str, str],
    Awaitable[tuple[DiscoveryAggregateResult, CollaborationSessionResult]],
]


class AMLDiscoveryGraph:
    def __init__(self, *, broadcast_func: BroadcastFunc | None = None) -> None:
        self.broadcast_func = broadcast_func or broadcast_discovery

    async def serve(
        self,
        prompt: str,
        *,
        investigation_type: str | InvestigationType | None = None,
    ) -> dict[str, object]:
        params = self.extract_params(prompt, investigation_type=investigation_type)
        if not params.has_all_params:
            missing = ", ".join(params.missing_params)
            raise ValueError(f"Missing required discovery fields: {missing}")
        if params.investigation_type is None:
            raise ValueError("Missing required discovery fields: investigation_type")
        result = await self.broadcast_func(
            params.investigation_type,
            params.case_id or "",
            params.entity_id or "",
            params.entity_name or "",
            params.case_context or "",
        )
        return {
            "text": format_discovery_summary(result),
            "aggregate_result": result.model_dump(mode="json"),
        }

    def extract_params(
        self,
        prompt: str,
        *,
        investigation_type: str | InvestigationType | None = None,
    ) -> DiscoveryPromptParams:
        case_match = re.search(r"\bcase\s+([A-Za-z0-9-]+)", prompt, re.IGNORECASE)
        entity_match = re.search(
            r"review\s+entity\s+(.+?)\s+with\s+entity\s+id\s+([A-Za-z0-9-]+)",
            prompt,
            re.IGNORECASE | re.DOTALL,
        )
        context_match = re.search(r"case\s+context:\s*(.+)$", prompt, re.IGNORECASE | re.DOTALL)

        params = DiscoveryPromptParams(
            investigation_type=resolve_investigation_type(
                explicit_investigation_type=investigation_type,
                prompt_text=prompt,
            ),
            case_id=case_match.group(1).strip() if case_match else None,
            entity_name=entity_match.group(1).strip() if entity_match else None,
            entity_id=entity_match.group(2).strip() if entity_match else None,
            case_context=context_match.group(1).strip() if context_match else None,
        )
        missing = [
            field_name
            for field_name in (
                "investigation_type",
                "case_id",
                "entity_id",
                "entity_name",
                "case_context",
            )
            if not getattr(params, field_name)
        ]
        params.missing_params = missing
        params.has_all_params = not missing
        return params


class AMLGroupCollaborationGraph:
    def __init__(self, *, collaboration_func: CollaborateFunc | None = None) -> None:
        self.collaboration_func = collaboration_func or run_discovery_and_collaboration

    async def serve(
        self,
        prompt: str,
        *,
        investigation_type: str | InvestigationType | None = None,
    ) -> dict[str, object]:
        params = AMLDiscoveryGraph().extract_params(prompt, investigation_type=investigation_type)
        if not params.has_all_params:
            missing = ", ".join(params.missing_params)
            raise ValueError(f"Missing required discovery fields: {missing}")
        if params.investigation_type is None:
            raise ValueError("Missing required discovery fields: investigation_type")
        discovery_result, collaboration_result = await self.collaboration_func(
            params.investigation_type,
            params.case_id or "",
            params.entity_id or "",
            params.entity_name or "",
            params.case_context or "",
        )
        return {
            "text": format_collaboration_summary(collaboration_result),
            "discovery_result": discovery_result.model_dump(mode="json"),
            "collaboration_result": collaboration_result.model_dump(mode="json"),
            "step_events": get_step_events(
                case_id=discovery_result.case_id,
                since_id=0,
                investigation_type=discovery_result.investigation_type.value,
                transport_lane=discovery_result.transport_lane,
            ),
        }
