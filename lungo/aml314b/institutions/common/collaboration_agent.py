from __future__ import annotations

from aml314b.common.channeling import InvestigationType, validate_transport_metadata
from aml314b.common.enforcement import PlaceholderEnforcementLayer
from aml314b.common.schemas import CollaborationContribution, CollaborationSessionRequest
from aml314b.common.stores import CuratedInvestigativeContextStore


class InstitutionCollaborationAgent:
    def __init__(
        self,
        institution_id: str,
        investigative_context_store: CuratedInvestigativeContextStore,
        enforcement: PlaceholderEnforcementLayer,
        transport_name: str = "A2A",
        supported_investigation_types: tuple[InvestigationType, ...] | None = None,
        expected_investigation_type: InvestigationType | None = None,
        expected_transport_lane: str | None = None,
    ) -> None:
        self.institution_id = institution_id
        self.investigative_context_store = investigative_context_store
        self.enforcement = enforcement
        self.transport_name = transport_name
        self.supported_investigation_types = supported_investigation_types
        self.expected_investigation_type = expected_investigation_type
        self.expected_transport_lane = expected_transport_lane

    async def contribute(self, request: CollaborationSessionRequest) -> CollaborationContribution:
        enforced_request = self.enforcement.enforce_inbound_collaboration_request(request)
        validate_transport_metadata(
            investigation_type=enforced_request.investigation_type,
            transport_name=self.transport_name,
            transport_lane=enforced_request.transport_lane,
            expected_investigation_type=self.expected_investigation_type,
            expected_transport_lane=self.expected_transport_lane,
        )
        if (
            self.supported_investigation_types is not None
            and enforced_request.investigation_type not in self.supported_investigation_types
        ):
            raise ValueError(
                f"{self.institution_id} is not configured for "
                f"{enforced_request.investigation_type.value}."
            )
        if self.institution_id not in enforced_request.participant_institution_ids:
            raise ValueError(
                f"{self.institution_id} is not part of collaboration session "
                f"{enforced_request.session_id}."
            )
        if self.institution_id not in enforced_request.accepted_institutions:
            raise ValueError(
                f"{self.institution_id} did not accept discovery for case "
                f"{enforced_request.case_id}."
            )
        contribution = self.investigative_context_store.get_context(
            enforced_request.entity_id,
            enforced_request.case_id,
        )
        if not contribution:
            raise KeyError(
                f"No collaboration context found for institution_id={self.institution_id} "
                f"entity_id={enforced_request.entity_id} case_id={enforced_request.case_id}"
            )
        response = CollaborationContribution(
            session_id=enforced_request.session_id,
            investigation_type=enforced_request.investigation_type,
            transport_lane=enforced_request.transport_lane,
            case_id=enforced_request.case_id,
            institution_id=self.institution_id,
            contribution=contribution,
            sequence_number=enforced_request.accepted_institutions.index(self.institution_id) + 1,
        )
        return self.enforcement.enforce_outbound_collaboration_contribution(
            response,
            case_id=enforced_request.case_id,
        )
