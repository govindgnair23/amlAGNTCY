from __future__ import annotations

import logging

from aml314b.enforcement import PlaceholderEnforcementLayer
from aml314b.enforcement_disclosure import DisclosureContext, LayeredDisclosureEnforcer
from aml314b.schemas import B314Request, B314Response
from aml314b.step_events import StepEventCollector
from aml314b.stores import (
    KnownHighRiskEntitiesStore,
    CuratedInvestigativeContextStore,
    InternalInvestigationsTriggerStore,
)
from config.config import AML314B_ENABLE_TRACING

from fi_b import tools
from fi_b.risk import RiskClassifier, DeterministicRiskClassifier

logger = logging.getLogger("corto.aml314b.fi_b.agent")

if AML314B_ENABLE_TRACING:
    from ioa_observe.sdk.decorators import agent as observe_agent
else:
    def observe_agent(*_args, **_kwargs):
        def decorator(obj):
            return obj
        return decorator


@observe_agent(name="fi_b_responder_agent")
class ResponderAgent:
    """FI-B responder agent for Phase 1.a bilateral 314(b) exchange."""

    def __init__(
        self,
        known_high_risk_store: KnownHighRiskEntitiesStore,
        curated_context_store: CuratedInvestigativeContextStore,
        enforcement: PlaceholderEnforcementLayer,
        internal_investigations_store: InternalInvestigationsTriggerStore | None = None,
        risk_classifier: RiskClassifier | None = None,
        layered_disclosure_enforcer: LayeredDisclosureEnforcer | None = None,
        default_requester_institution_id: str = "FI-A",
        institution_id: str = "FI-B",
    ) -> None:
        self.known_high_risk_store = known_high_risk_store
        self.curated_context_store = curated_context_store
        self.enforcement = enforcement
        self.internal_investigations_store = internal_investigations_store
        self.risk_classifier = risk_classifier or DeterministicRiskClassifier()
        self.layered_disclosure_enforcer = layered_disclosure_enforcer
        self.default_requester_institution_id = default_requester_institution_id
        self.institution_id = institution_id

    async def evaluate_request(
        self,
        request: B314Request,
        *,
        step_collector: StepEventCollector | None = None,
        requester_institution_id: str | None = None,
    ) -> B314Response:
        """Evaluate an inbound 314(b) request and return a bounded response."""
        enforced_request = self.enforcement.enforce_inbound_request(request)
        if step_collector:
            step_collector.emit(
                "fi_b_preparing_response", "FI-B preparing response"
            )
        logger.info(
            "FI-B evaluating request case_id=%s entities=%s",
            enforced_request.case_id,
            enforced_request.entities,
        )

        matched_entities = tools.match_known_high_risk_entities(
            enforced_request.entities, self.known_high_risk_store
        )
        summary, has_curated_context, in_window = tools.build_bounded_context_summary(
            enforced_request, matched_entities, self.curated_context_store
        )

        if not matched_entities:
            match_type = "NO_MATCH"
            if enforced_request.activity_summary:
                risk_label = self.risk_classifier.classify_activity(
                    enforced_request.activity_summary
                )
                if risk_label != "NONE" and self.internal_investigations_store:
                    reason = (
                        "No known high-risk entity match, but activity summary was "
                        f"classified as {risk_label}."
                    )
                    tools.trigger_internal_investigation(
                        self.internal_investigations_store,
                        case_id=enforced_request.case_id,
                        entity_id=enforced_request.entities[0],
                        risk_label=risk_label,
                        reason=reason,
                    )
                    summary = (
                        "FI-B did not identify a known high-risk entity match, but "
                        f"an internal investigation was triggered for case {enforced_request.case_id} "
                        f"based on activity risk classification {risk_label}."
                    )
        elif has_curated_context and in_window:
            match_type = "CONFIRMED_MATCH"
        elif has_curated_context and not in_window:
            match_type = "POTENTIAL_MATCH"
            summary = (
                "FI-B identified a matching entity, but observed activity outside the "
                f"requested time window for case {enforced_request.case_id}. {summary}"
            )
        else:
            match_type = "POTENTIAL_MATCH"

        response = B314Response(
            in_reply_to=enforced_request.message_id,
            match_type=match_type,
            summary=summary,
        )

        if self.layered_disclosure_enforcer is not None:
            context = DisclosureContext(
                case_id=enforced_request.case_id,
                requester_institution=(
                    requester_institution_id
                    or self.default_requester_institution_id
                ),
                responder_institution=self.institution_id,
                entity_ids=list(enforced_request.entities),
                request_message_id=enforced_request.message_id,
            )
            response = self.layered_disclosure_enforcer.enforce_outbound_response(
                context=context,
                response=response,
            )

        enforced_response = self.enforcement.enforce_outbound_response(
            response, case_id=enforced_request.case_id
        )
        if step_collector:
            step_collector.emit(
                "fi_b_response_reviewed",
                "FI-B response reviewed for policy violation",
            )
        logger.info(
            "FI-B response case_id=%s match_type=%s message_id=%s",
            enforced_request.case_id,
            enforced_response.match_type,
            enforced_response.message_id,
        )
        if step_collector:
            step_collector.emit("fi_b_response_sent", "FI-B response sent")
        return enforced_response
