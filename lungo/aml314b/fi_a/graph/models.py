from __future__ import annotations

from pydantic import BaseModel, Field

from aml314b.common.channeling import InvestigationType


class DiscoveryPromptParams(BaseModel):
    investigation_type: InvestigationType | None = None
    case_id: str | None = None
    entity_id: str | None = None
    entity_name: str | None = None
    case_context: str | None = None
    has_all_params: bool = False
    missing_params: list[str] = Field(default_factory=list)
