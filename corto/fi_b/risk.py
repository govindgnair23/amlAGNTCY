from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage

from common.llm import get_llm

logger = logging.getLogger("corto.aml314b.fi_b.risk")

RISK_LABELS = {
    "TERRORIST_FINANCING",
    "HUMAN_TRAFFICKING",
    "NONE",
}


class RiskClassifier(Protocol):
    def classify_activity(self, activity_summary: str) -> str:
        ...


@dataclass
class DeterministicRiskClassifier:
    """Simple keyword-based classifier for deterministic tests."""

    def classify_activity(self, activity_summary: str) -> str:
        summary = (activity_summary or "").lower()
        if "terror" in summary:
            return "TERRORIST_FINANCING"
        if "human trafficking" in summary or "trafficking" in summary:
            return "HUMAN_TRAFFICKING"
        return "NONE"


@dataclass
class LLMRiskClassifier:
    """LLM-backed classifier that returns a single risk label."""

    def classify_activity(self, activity_summary: str) -> str:
        summary = (activity_summary or "").strip()
        if not summary:
            return "NONE"

        system_prompt = (
            "You classify 314(b) activity summaries into one label: "
            "TERRORIST_FINANCING, HUMAN_TRAFFICKING, or NONE. "
            "Return only the label, no extra text."
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=summary),
        ]
        response = get_llm().invoke(messages)
        label = (getattr(response, "content", "") or "").strip().upper()
        if label not in RISK_LABELS:
            logger.warning("Unrecognized risk label from LLM: %s", label)
            return "NONE"
        return label
