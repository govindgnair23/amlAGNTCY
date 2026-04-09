from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage

from aml314b.schemas import B314Response
from common.llm import get_llm
from aml314b.enforcement_disclosure.types import DisclosureContext

logger = logging.getLogger("corto.aml314b.enforcement_disclosure.critic")

LIKELIHOOD_LEVELS = (
    "VERY_UNLIKELY",
    "UNLIKELY",
    "LIKELY",
    "VERY_LIKELY",
)


@dataclass(frozen=True)
class CriticDecision:
    allowed: bool
    reason_code: str
    rationale: str
    raw_response: str
    likelihood: str | None = None


class DisclosureCritic(Protocol):
    def review_single_turn(
        self,
        *,
        policy_text: str,
        context: DisclosureContext,
        response: B314Response,
    ) -> CriticDecision:
        ...

    def review_cumulative(
        self,
        *,
        policy_text: str,
        context: DisclosureContext,
        entity_id: str,
        history_summaries: list[str],
        response: B314Response,
    ) -> CriticDecision:
        ...


@dataclass
class LLMDisclosureCritic:
    """LLM-backed policy critic for single-turn and cumulative disclosure checks."""

    def review_single_turn(
        self,
        *,
        policy_text: str,
        context: DisclosureContext,
        response: B314Response,
    ) -> CriticDecision:
        system_prompt = (
            "You are a strict AML 314(b) disclosure policy critic. "
            "Evaluate only policy compliance, not investigative usefulness. "
            "Return strict JSON with keys decision, reason_code, rationale. "
            "decision must be ALLOW or BLOCK."
        )
        human_prompt = (
            f"Policy:\n{policy_text}\n\n"
            f"Case ID: {context.case_id}\n"
            f"Requester Institution: {context.requester_institution}\n"
            f"Responder Institution: {context.responder_institution}\n"
            f"Entities: {', '.join(context.entity_ids)}\n"
            f"Response Summary:\n{response.summary}"
        )
        return self._invoke(system_prompt=system_prompt, human_prompt=human_prompt)

    def review_cumulative(
        self,
        *,
        policy_text: str,
        context: DisclosureContext,
        entity_id: str,
        history_summaries: list[str],
        response: B314Response,
    ) -> CriticDecision:
        history_lines = [
            f"{index + 1}. {summary}" for index, summary in enumerate(history_summaries)
        ]
        history_text = "\n".join(history_lines) if history_lines else "<none>"
        system_prompt = (
            "You are a strict AML 314(b) cumulative disclosure policy critic. "
            "Decide whether the NEW message, when combined with prior disclosures, violates policy. "
            "Also classify how strongly the combined disclosures indicate the customer is high net worth. "
            "Return strict JSON with keys decision, reason_code, rationale, likelihood. "
            "decision must be ALLOW or BLOCK. "
            "likelihood must be one of VERY_UNLIKELY, UNLIKELY, LIKELY, VERY_LIKELY."
        )
        human_prompt = (
            f"Policy:\n{policy_text}\n\n"
            f"Case ID: {context.case_id}\n"
            f"Requester Institution: {context.requester_institution}\n"
            f"Responder Institution: {context.responder_institution}\n"
            f"Entity: {entity_id}\n\n"
            f"Prior Disclosures For This Requester+Entity:\n{history_text}\n\n"
            f"New Candidate Disclosure:\n{response.summary}"
        )
        return self._invoke(system_prompt=system_prompt, human_prompt=human_prompt)

    def _invoke(self, *, system_prompt: str, human_prompt: str) -> CriticDecision:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ]
        response = get_llm().invoke(messages)
        raw = (getattr(response, "content", "") or "").strip()
        parsed = _parse_critic_json(raw)
        return CriticDecision(
            allowed=parsed["decision"] == "ALLOW",
            reason_code=parsed["reason_code"],
            rationale=parsed["rationale"],
            raw_response=raw,
            likelihood=parsed["likelihood"],
        )


def _parse_critic_json(raw_response: str) -> dict[str, str | None]:
    text = raw_response.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"Critic returned non-JSON response: {raw_response}")

    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse critic response as JSON: %s", raw_response)
        raise ValueError("Critic response was not valid JSON") from exc

    decision = str(payload.get("decision", "")).strip().upper()
    reason_code = str(payload.get("reason_code", "UNKNOWN")).strip().upper() or "UNKNOWN"
    rationale = str(payload.get("rationale", "")).strip() or "No rationale provided"

    if decision not in {"ALLOW", "BLOCK"}:
        raise ValueError(f"Critic decision must be ALLOW or BLOCK, got: {decision}")

    likelihood_raw = payload.get("likelihood")
    likelihood: str | None = None
    if likelihood_raw is not None and str(likelihood_raw).strip():
        likelihood = (
            str(likelihood_raw)
            .strip()
            .upper()
            .replace("-", "_")
            .replace(" ", "_")
        )
        if likelihood not in LIKELIHOOD_LEVELS:
            raise ValueError(
                "Critic likelihood must be one of "
                f"{', '.join(LIKELIHOOD_LEVELS)}, got: {likelihood}"
            )

    return {
        "decision": decision,
        "reason_code": reason_code,
        "rationale": rationale,
        "likelihood": likelihood,
    }
