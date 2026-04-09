from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from nats import connect as nats_connect
from nats.aio.client import Client as NATS
from nats.aio.msg import Msg
from pydantic import BaseModel, Field, field_validator

from aml314b.common.channeling import InvestigationType, describe_investigation_lane


LaneProbeDecision = Literal["YES"]
CandidateResolutionSource = Literal["NATS_LANE_PROBE"]


def build_lane_probe_subject(value: str | InvestigationType) -> str:
    descriptor = describe_investigation_lane(value)
    return f"aml314b.probe.{descriptor.topic_suffix}"


def normalize_candidate_institutions(values: list[str]) -> list[str]:
    return sorted({value.strip().upper() for value in values if value and value.strip()})


class LaneProbeRequest(BaseModel):
    probe_id: str = Field(default_factory=lambda: f"probe-{uuid4()}")
    requestor_institution_id: str
    investigation_type: InvestigationType
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("requestor_institution_id")
    @classmethod
    def validate_requestor_institution_id(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("requestor_institution_id must be non-empty")
        return cleaned


class LaneProbeResponse(BaseModel):
    probe_id: str
    responder_institution_id: str
    investigation_type: InvestigationType
    decision: LaneProbeDecision = "YES"
    responded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("probe_id", "responder_institution_id")
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:
        cleaned = value.strip().upper() if info.field_name == "responder_institution_id" else value.strip()
        if not cleaned:
            raise ValueError(f"{info.field_name} must be non-empty")
        return cleaned


class LaneProbeResult(BaseModel):
    probe_id: str
    investigation_type: InvestigationType
    candidate_institutions: list[str]
    candidate_response_count: int
    candidate_resolution_source: CandidateResolutionSource = "NATS_LANE_PROBE"
    responses: list[LaneProbeResponse]

    @field_validator("candidate_institutions")
    @classmethod
    def validate_candidate_institutions(cls, values: list[str]) -> list[str]:
        return normalize_candidate_institutions(values)


class LaneProbeNatsClient:
    def __init__(
        self,
        *,
        endpoint: str,
        response_timeout_ms: int,
        client_name: str = "lungo.aml314b.fi_a.probe",
    ) -> None:
        self.endpoint = endpoint
        self.response_timeout_ms = response_timeout_ms
        self.client_name = client_name

    async def collect(self, request: LaneProbeRequest) -> list[LaneProbeResponse]:
        nc = await _connect_with_retries(self.endpoint, name=self.client_name)
        inbox = nc.new_inbox()
        responses: list[LaneProbeResponse] = []
        queue: asyncio.Queue[LaneProbeResponse] = asyncio.Queue()

        async def response_callback(msg: Msg) -> None:
            await self._handle_response_message(msg, queue)

        subscription = await nc.subscribe(
            inbox,
            cb=response_callback,
        )
        try:
            await nc.publish(
                build_lane_probe_subject(request.investigation_type),
                request.model_dump_json().encode("utf-8"),
                reply=inbox,
            )
            await nc.flush()
            deadline = asyncio.get_running_loop().time() + (self.response_timeout_ms / 1000)
            while True:
                timeout_s = deadline - asyncio.get_running_loop().time()
                if timeout_s <= 0:
                    break
                try:
                    response = await asyncio.wait_for(queue.get(), timeout=timeout_s)
                except TimeoutError:
                    break
                if (
                    response.probe_id == request.probe_id
                    and response.investigation_type == request.investigation_type
                    and response.decision == "YES"
                ):
                    responses.append(response)
            return responses
        finally:
            await subscription.unsubscribe()
            await nc.drain()

    async def _handle_response_message(
        self,
        msg: Msg,
        queue: asyncio.Queue[LaneProbeResponse],
    ) -> None:
        try:
            payload = json.loads(msg.data.decode("utf-8"))
            response = LaneProbeResponse.model_validate(payload)
        except Exception:
            return
        queue.put_nowait(response)


class LaneProbeResponderRuntime:
    def __init__(
        self,
        *,
        institution_id: str,
        supported_investigation_types: tuple[InvestigationType, ...],
        endpoint: str,
        logger_name: str | None = None,
    ) -> None:
        self.institution_id = institution_id.strip().upper()
        self.supported_investigation_types = supported_investigation_types
        self.endpoint = endpoint
        self.logger = logging.getLogger(logger_name or f"lungo.aml314b.{self.institution_id.lower()}.probe")
        self._nc: NATS | None = None
        self._subscriptions = []

    async def start(self) -> None:
        if not self.supported_investigation_types:
            return
        self._nc = await _connect_with_retries(
            self.endpoint,
            name=f"lungo.aml314b.{self.institution_id.lower()}.probe",
        )
        for investigation_type in self.supported_investigation_types:
            subject = build_lane_probe_subject(investigation_type)

            async def probe_callback(
                msg: Msg,
                expected: InvestigationType = investigation_type,
            ) -> None:
                await self._handle_probe_message(msg, expected)

            subscription = await self._nc.subscribe(
                subject,
                cb=probe_callback,
            )
            self._subscriptions.append(subscription)

    async def close(self) -> None:
        if self._nc is None:
            return
        await self._nc.drain()
        self._subscriptions.clear()
        self._nc = None

    async def _handle_probe_message(
        self,
        msg: Msg,
        expected_investigation_type: InvestigationType,
    ) -> None:
        if self._nc is None or not msg.reply:
            return
        try:
            payload = json.loads(msg.data.decode("utf-8"))
            request = LaneProbeRequest.model_validate(payload)
        except Exception:
            self.logger.debug("Ignoring invalid lane probe payload.")
            return
        if request.investigation_type != expected_investigation_type:
            self.logger.debug(
                "Ignoring probe for %s on %s subscription.",
                request.investigation_type.value,
                expected_investigation_type.value,
            )
            return
        response = LaneProbeResponse(
            probe_id=request.probe_id,
            responder_institution_id=self.institution_id,
            investigation_type=request.investigation_type,
        )
        await self._nc.publish(
            msg.reply,
            response.model_dump_json().encode("utf-8"),
        )


async def _connect_with_retries(
    endpoint: str,
    *,
    name: str,
    attempts: int = 10,
    delay_s: float = 0.2,
) -> NATS:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return await nats_connect(servers=[endpoint], name=name)
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(delay_s)
    if last_error is not None:
        raise last_error
    raise RuntimeError("NATS connection failed without an exception.")
