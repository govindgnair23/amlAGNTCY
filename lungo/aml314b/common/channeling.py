from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class InvestigationType(str, Enum):
    MONEY_MULE = "MONEY_MULE"
    TERRORIST_FINANCING = "TERRORIST_FINANCING"


@dataclass(frozen=True)
class InvestigationLaneDescriptor:
    investigation_type: InvestigationType
    lane_label: str
    lane_key: str
    transport_lane: str
    topic_suffix: str


_INVESTIGATION_METADATA = {
    InvestigationType.MONEY_MULE: {
        "label": "money mule",
        "lane_key": "money_mule",
    },
    InvestigationType.TERRORIST_FINANCING: {
        "label": "terrorist financing",
        "lane_key": "terrorist_financing",
    },
}

_INVESTIGATION_ALIASES = {
    "MONEY_MULE": InvestigationType.MONEY_MULE,
    "MONEY MULE": InvestigationType.MONEY_MULE,
    "MONEY-MULE": InvestigationType.MONEY_MULE,
    "TERRORIST_FINANCING": InvestigationType.TERRORIST_FINANCING,
    "TERRORIST FINANCING": InvestigationType.TERRORIST_FINANCING,
    "TERRORIST-FINANCING": InvestigationType.TERRORIST_FINANCING,
}

_PROMPT_PATTERNS = {
    InvestigationType.MONEY_MULE: re.compile(r"\bmoney(?:[\s_-]+)mule\b", re.IGNORECASE),
    InvestigationType.TERRORIST_FINANCING: re.compile(
        r"\bterrorist(?:[\s_-]+)financing\b",
        re.IGNORECASE,
    ),
}


def normalize_investigation_type(value: str | InvestigationType) -> InvestigationType:
    if isinstance(value, InvestigationType):
        return value
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("investigation_type must be non-empty")
    normalized_key = re.sub(r"[\s-]+", "_", cleaned).upper()
    normalized = _INVESTIGATION_ALIASES.get(normalized_key) or _INVESTIGATION_ALIASES.get(
        normalized_key.replace("_", " ")
    )
    if normalized is None:
        supported = ", ".join(investigation_type.value for investigation_type in InvestigationType)
        raise ValueError(
            "Unsupported investigation_type. "
            f"Expected one of: {supported}."
        )
    return normalized


def extract_investigation_type_from_text(text: str) -> InvestigationType | None:
    matches = [
        investigation_type
        for investigation_type, pattern in _PROMPT_PATTERNS.items()
        if pattern.search(text)
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(
            "Prompt references multiple investigation types. "
            "Specify only one supported investigation type."
        )
    return matches[0]


def resolve_investigation_type(
    *,
    explicit_investigation_type: str | InvestigationType | None = None,
    prompt_text: str | None = None,
) -> InvestigationType | None:
    prompt_investigation_type = (
        extract_investigation_type_from_text(prompt_text or "")
        if prompt_text is not None
        else None
    )
    if explicit_investigation_type is None:
        return prompt_investigation_type

    normalized = normalize_investigation_type(explicit_investigation_type)
    if prompt_investigation_type and prompt_investigation_type != normalized:
        raise ValueError(
            "Explicit investigation_type does not match the investigation type found in the prompt."
        )
    return normalized


def describe_investigation_lane(
    value: str | InvestigationType,
) -> InvestigationLaneDescriptor:
    investigation_type = normalize_investigation_type(value)
    metadata = _INVESTIGATION_METADATA[investigation_type]
    lane_key = str(metadata["lane_key"])
    return InvestigationLaneDescriptor(
        investigation_type=investigation_type,
        lane_label=str(metadata["label"]),
        lane_key=lane_key,
        transport_lane=f"aml314b.{lane_key}",
        topic_suffix=lane_key,
    )


def build_lane_scoped_topic(base_topic: str, value: str | InvestigationType) -> str:
    topic = base_topic.strip()
    if not topic:
        raise ValueError("base_topic must be non-empty")
    return f"{topic}.{describe_investigation_lane(value).topic_suffix}"


def validate_transport_metadata(
    *,
    investigation_type: str | InvestigationType,
    transport_name: str,
    transport_lane: str | None = None,
    expected_investigation_type: str | InvestigationType | None = None,
    expected_transport_lane: str | None = None,
) -> InvestigationLaneDescriptor:
    descriptor = describe_investigation_lane(investigation_type)
    normalized_transport = transport_name.strip().upper()

    if expected_investigation_type is not None:
        expected = normalize_investigation_type(expected_investigation_type)
        if descriptor.investigation_type != expected:
            raise ValueError(
                "investigation_type does not match the registered investigation lane."
            )

    if normalized_transport == "SLIM":
        if transport_lane is None or not transport_lane.strip():
            raise ValueError("SLIM AML payloads must include transport_lane metadata.")
        if transport_lane.strip() != descriptor.transport_lane:
            raise ValueError("transport_lane does not match investigation_type.")
        if expected_transport_lane is not None and transport_lane.strip() != expected_transport_lane:
            raise ValueError("transport_lane does not match the registered SLIM lane.")
    return descriptor
