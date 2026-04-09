from __future__ import annotations

from typing import Iterable

from aml314b.schemas import B314Request
from aml314b.stores import (
    KnownHighRiskEntitiesStore,
    CuratedInvestigativeContextStore,
    InternalInvestigationsTriggerStore,
)

TOOLS = [
    {
        "name": "match_known_high_risk_entities",
        "description": "Return the subset of requested entities that exist in FI-B's KnownHighRiskEntitiesStore.",
    },
    {
        "name": "build_bounded_context_summary",
        "description": "Build a bounded 314(b)-compliant summary using CuratedInvestigativeContextStore.",
    },
    {
        "name": "trigger_internal_investigation",
        "description": "Append a record to FI-B's InternalInvestigationsTriggerStore.",
    },
]


def match_known_high_risk_entities(
    entity_ids: Iterable[str], known_store: KnownHighRiskEntitiesStore
) -> list[str]:
    return known_store.match_entities(entity_ids)


def build_bounded_context_summary(
    request: B314Request,
    matched_entities: list[str],
    context_store: CuratedInvestigativeContextStore,
    max_chars: int = 500,
) -> tuple[str, bool, bool]:
    if not matched_entities:
        summary = (
            "No matching entities were identified within FI-B's known high-risk entity store "
            f"for case {request.case_id}."
        )
        return summary[:max_chars], False, False

    for entity_id in matched_entities:
        curated_context = context_store.get_context(entity_id, case_id=request.case_id)
        if curated_context and curated_context.summary:
            in_window = _is_context_within_request_window(request, curated_context)
            window_note = ""
            if curated_context.activity_start and curated_context.activity_end:
                window_note = (
                    " Observed activity window was "
                    f"{curated_context.activity_start.date()} to {curated_context.activity_end.date()}."
                )
            summary = (
                f"FI-B located curated investigative context for entity {entity_id} "
                f"within case scope {request.case_id}: {curated_context.summary}{window_note}"
            )
            return summary[:max_chars], True, in_window

    summary = (
        "FI-B identified a potential entity match but has no curated investigative context "
        f"available for the requested case scope {request.case_id}."
    )
    return summary[:max_chars], False, False


def trigger_internal_investigation(
    store: InternalInvestigationsTriggerStore,
    case_id: str,
    entity_id: str,
    risk_label: str,
    reason: str,
) -> None:
    store.append_trigger(
        case_id=case_id,
        entity_id=entity_id,
        risk_label=risk_label,
        reason=reason,
    )


def _is_context_within_request_window(
    request: B314Request,
    context: CuratedInvestigativeContextStore.CuratedContext,
) -> bool:
    if not context.activity_start or not context.activity_end:
        return True
    request_start = request.time_window.start
    request_end = request.time_window.end
    return not (context.activity_end < request_start or context.activity_start > request_end)
