from __future__ import annotations

from aml314b.common.channeling import InvestigationType, validate_transport_metadata
from aml314b.common.enforcement import PlaceholderEnforcementLayer
from aml314b.common.schemas import DiscoveryRequest, DiscoveryResponse
from aml314b.common.stores import KnownHighRiskEntitiesStore


class InstitutionDiscoveryAgent:
    def __init__(
        self,
        institution_id: str,
        known_high_risk_store: KnownHighRiskEntitiesStore,
        enforcement: PlaceholderEnforcementLayer,
        transport_name: str = "A2A",
        supported_investigation_types: tuple[InvestigationType, ...] | None = None,
        expected_investigation_type: InvestigationType | None = None,
        expected_transport_lane: str | None = None,
    ) -> None:
        self.institution_id = institution_id
        self.known_high_risk_store = known_high_risk_store
        self.enforcement = enforcement
        self.transport_name = transport_name
        self.supported_investigation_types = supported_investigation_types
        self.expected_investigation_type = expected_investigation_type
        self.expected_transport_lane = expected_transport_lane

    async def evaluate_request(self, request: DiscoveryRequest) -> DiscoveryResponse:
        enforced_request = self.enforcement.enforce_inbound_discovery_request(request)
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
        accepted = self.known_high_risk_store.has_entity(enforced_request.entity_id)
        response = DiscoveryResponse(
            in_reply_to=enforced_request.message_id,
            responder_institution_id=self.institution_id,
            investigation_type=enforced_request.investigation_type,
            transport_lane=enforced_request.transport_lane,
            case_id=enforced_request.case_id,
            entity_id=enforced_request.entity_id,
            decision="ACCEPT" if accepted else "DECLINE",
            reason=(
                "Entity present in known high risk entities store."
                if accepted
                else "Entity not present in known high risk entities store."
            ),
        )
        return self.enforcement.enforce_outbound_discovery_response(
            response,
            case_id=enforced_request.case_id,
        )
