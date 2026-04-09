from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from aml314b.schemas import B314Request, B314Response, TimeWindow


@dataclass(frozen=True)
class ActiveCase:
    case_id: str
    entity_id: str
    counterparty_id: str
    time_window_start: datetime
    time_window_end: datetime
    status: str
    activity_summary: str | None = None

    def to_time_window(self) -> TimeWindow:
        return TimeWindow(start=self.time_window_start, end=self.time_window_end)


class ActiveInvestigationsStore:
    REQUIRED_COLUMNS = {
        "case_id",
        "entity_id",
        "counterparty_id",
        "time_window_start",
        "time_window_end",
        "status",
    }

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)
        self._df = self._load_dataframe()

    def list_active_cases(self) -> list[ActiveCase]:
        active_df = self._df[self._df["status"].str.upper() == "ACTIVE"].copy()
        if active_df.empty:
            active_df = self._df.copy()
        return [self._row_to_case(row) for _, row in active_df.iterrows()]

    def get_case(self, case_id: str) -> ActiveCase:
        matches = self._df[self._df["case_id"] == case_id]
        if matches.empty:
            raise KeyError(f"No active investigation found for case_id={case_id}")
        return self._row_to_case(matches.iloc[0])

    def _load_dataframe(self) -> pd.DataFrame:
        df = pd.read_csv(self.csv_path)
        missing = self.REQUIRED_COLUMNS.difference(df.columns)
        if missing:
            raise ValueError(
                f"ActiveInvestigationsStore missing required columns: {sorted(missing)}"
            )
        df["time_window_start"] = pd.to_datetime(df["time_window_start"], utc=True)
        df["time_window_end"] = pd.to_datetime(df["time_window_end"], utc=True)
        df["status"] = df["status"].fillna("ACTIVE").astype(str)
        return df

    def _row_to_case(self, row: pd.Series) -> ActiveCase:
        activity_summary = None
        if "case_summary" in row:
            value = row.get("case_summary")
            if pd.notna(value):
                activity_summary = str(value)
        return ActiveCase(
            case_id=str(row["case_id"]),
            entity_id=str(row["entity_id"]),
            counterparty_id=str(row["counterparty_id"]),
            time_window_start=row["time_window_start"].to_pydatetime(),
            time_window_end=row["time_window_end"].to_pydatetime(),
            status=str(row["status"]),
            activity_summary=activity_summary,
        )


@dataclass(frozen=True)
class DirectoryRoute:
    institution_id: str
    transport: str
    endpoint: str
    enabled: bool


class CounterpartyDirectoryStore:
    REQUIRED_COLUMNS = {"institution_id", "transport", "endpoint", "enabled"}

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)
        self._df = self._load_dataframe()
        self._routes = self._build_routes()

    def get_route(self, institution_id: str, transport: str) -> DirectoryRoute:
        key = (institution_id.strip().upper(), transport.strip().upper())
        route = self._routes.get(key)
        if route is None:
            raise ValueError(
                "No directory route found for "
                f"institution_id={institution_id} transport={transport}"
            )
        if not route.enabled:
            raise ValueError(
                "Directory route is disabled for "
                f"institution_id={institution_id} transport={transport}"
            )
        return route

    def _load_dataframe(self) -> pd.DataFrame:
        df = pd.read_csv(self.csv_path)
        missing = self.REQUIRED_COLUMNS.difference(df.columns)
        if missing:
            raise ValueError(
                f"CounterpartyDirectoryStore missing required columns: {sorted(missing)}"
            )
        df["institution_id"] = df["institution_id"].astype(str).str.strip()
        df["transport"] = df["transport"].astype(str).str.strip().str.upper()
        df["endpoint"] = df["endpoint"].astype(str).str.strip()
        df["enabled"] = (
            df["enabled"]
            .astype(str)
            .str.strip()
            .str.lower()
            .isin({"1", "true", "yes", "y"})
        )
        return df

    def _build_routes(self) -> dict[tuple[str, str], DirectoryRoute]:
        routes: dict[tuple[str, str], DirectoryRoute] = {}
        for _, row in self._df.iterrows():
            institution_id = str(row["institution_id"]).upper()
            transport = str(row["transport"]).upper()
            route = DirectoryRoute(
                institution_id=str(row["institution_id"]),
                transport=transport,
                endpoint=str(row["endpoint"]),
                enabled=bool(row["enabled"]),
            )
            routes[(institution_id, transport)] = route
        return routes


class KnownHighRiskEntitiesStore:
    REQUIRED_COLUMNS = {"entity_id", "entity_name", "risk_level"}

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)
        self._df = self._load_dataframe()
        self._entity_set = set(self._df["entity_id"].astype(str))

    def has_entity(self, entity_id: str) -> bool:
        return entity_id in self._entity_set

    def match_entities(self, entity_ids: Iterable[str]) -> list[str]:
        return [entity_id for entity_id in entity_ids if entity_id in self._entity_set]

    def _load_dataframe(self) -> pd.DataFrame:
        df = pd.read_csv(self.csv_path)
        missing = self.REQUIRED_COLUMNS.difference(df.columns)
        if missing:
            raise ValueError(
                f"KnownHighRiskEntitiesStore missing required columns: {sorted(missing)}"
            )
        df["entity_id"] = df["entity_id"].astype(str)
        return df


class CuratedInvestigativeContextStore:
    REQUIRED_COLUMNS = {"entity_id", "summary"}
    OPTIONAL_COLUMNS = {"case_id", "activity_start", "activity_end"}

    @dataclass(frozen=True)
    class CuratedContext:
        entity_id: str
        case_id: str | None
        summary: str
        activity_start: datetime | None
        activity_end: datetime | None

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)
        self._df = self._load_dataframe()
        self._contexts = self._build_contexts()

    def get_context(self, entity_id: str, case_id: str | None = None) -> CuratedContext | None:
        if case_id:
            for context in self._contexts:
                if context.entity_id == entity_id and context.case_id == case_id:
                    return context
        for context in self._contexts:
            if context.entity_id == entity_id and context.case_id is None:
                return context
        return None

    def _load_dataframe(self) -> pd.DataFrame:
        df = pd.read_csv(self.csv_path)
        missing = self.REQUIRED_COLUMNS.difference(df.columns)
        if missing:
            raise ValueError(
                f"CuratedInvestigativeContextStore missing required columns: {sorted(missing)}"
            )
        df["entity_id"] = df["entity_id"].astype(str)
        df["summary"] = df["summary"].fillna("").astype(str)
        if "case_id" in df.columns:
            df["case_id"] = df["case_id"].fillna("").astype(str)
        if "activity_start" in df.columns:
            df["activity_start"] = pd.to_datetime(df["activity_start"], utc=True, errors="coerce")
        if "activity_end" in df.columns:
            df["activity_end"] = pd.to_datetime(df["activity_end"], utc=True, errors="coerce")
        return df

    def _build_contexts(self) -> list[CuratedContext]:
        contexts: list[CuratedContext] = []
        for _, row in self._df.iterrows():
            case_id = None
            if "case_id" in self._df.columns:
                case_id_value = str(row.get("case_id", "")).strip()
                if case_id_value:
                    case_id = case_id_value
            activity_start = None
            activity_end = None
            if "activity_start" in self._df.columns:
                value = row.get("activity_start")
                if pd.notna(value):
                    activity_start = value.to_pydatetime()
            if "activity_end" in self._df.columns:
                value = row.get("activity_end")
                if pd.notna(value):
                    activity_end = value.to_pydatetime()
            contexts.append(
                CuratedInvestigativeContextStore.CuratedContext(
                    entity_id=str(row["entity_id"]),
                    case_id=case_id,
                    summary=str(row["summary"]),
                    activity_start=activity_start,
                    activity_end=activity_end,
                )
            )
        return contexts


class RetrievedInformationStore:
    REQUIRED_COLUMNS = [
        "case_id",
        "request_message_id",
        "response_message_id",
        "in_reply_to",
        "match_type",
        "summary",
        "source_institution",
        "usage_purpose",
        "retention",
        "received_at",
    ]

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)

    def append_response(
        self,
        request: B314Request,
        response: B314Response,
        source_institution: str,
    ) -> None:
        record = {
            "case_id": request.case_id,
            "request_message_id": request.message_id,
            "response_message_id": response.message_id,
            "in_reply_to": response.in_reply_to,
            "match_type": response.match_type,
            "summary": response.summary,
            "source_institution": source_institution,
            "usage_purpose": response.usage_constraints.purpose,
            "retention": response.usage_constraints.retention,
            "received_at": response.responded_at.isoformat(),
        }
        self.append_record(record)

    def append_record(self, record: dict) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([record], columns=self.REQUIRED_COLUMNS)
        header = not self.csv_path.exists()
        df.to_csv(self.csv_path, mode="a", index=False, header=header)

    def read_all(self) -> pd.DataFrame:
        if not self.csv_path.exists():
            return pd.DataFrame(columns=self.REQUIRED_COLUMNS)
        return pd.read_csv(self.csv_path)


class InternalInvestigationsTriggerStore:
    REQUIRED_COLUMNS = [
        "case_id",
        "entity_id",
        "risk_label",
        "reason",
        "triggered_at",
    ]

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)

    def append_trigger(self, case_id: str, entity_id: str, risk_label: str, reason: str) -> None:
        record = {
            "case_id": case_id,
            "entity_id": entity_id,
            "risk_label": risk_label,
            "reason": reason,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        }
        self.append_record(record)

    def append_record(self, record: dict) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([record], columns=self.REQUIRED_COLUMNS)
        header = not self.csv_path.exists()
        df.to_csv(self.csv_path, mode="a", index=False, header=header)

    def read_all(self) -> pd.DataFrame:
        if not self.csv_path.exists():
            return pd.DataFrame(columns=self.REQUIRED_COLUMNS)
        return pd.read_csv(self.csv_path)


@dataclass(frozen=True)
class DisclosureAuditRecord:
    review_id: str
    case_id: str
    requester_institution: str
    responder_institution: str
    entity_id: str
    request_message_id: str
    response_message_id: str
    in_reply_to: str
    match_type: str
    summary: str
    allowed: bool
    blocked_layer: str
    reasons: str
    layer_decisions_json: str
    reviewed_at: str
    sent: bool


class DisclosureAuditStore:
    REQUIRED_COLUMNS = [
        "review_id",
        "case_id",
        "requester_institution",
        "responder_institution",
        "entity_id",
        "request_message_id",
        "response_message_id",
        "in_reply_to",
        "match_type",
        "summary",
        "allowed",
        "blocked_layer",
        "reasons",
        "layer_decisions_json",
        "reviewed_at",
        "sent",
    ]

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)

    def append_review(
        self,
        *,
        review_id: str,
        case_id: str,
        requester_institution: str,
        responder_institution: str,
        entity_id: str,
        request_message_id: str,
        response_message_id: str,
        in_reply_to: str,
        match_type: str,
        summary: str,
        allowed: bool,
        blocked_layer: str | None,
        reasons: str,
        layer_decisions_json: str,
        reviewed_at: str,
        sent: bool,
    ) -> None:
        record = {
            "review_id": review_id,
            "case_id": case_id,
            "requester_institution": requester_institution,
            "responder_institution": responder_institution,
            "entity_id": entity_id,
            "request_message_id": request_message_id,
            "response_message_id": response_message_id,
            "in_reply_to": in_reply_to,
            "match_type": match_type,
            "summary": summary,
            "allowed": allowed,
            "blocked_layer": blocked_layer or "",
            "reasons": reasons,
            "layer_decisions_json": layer_decisions_json,
            "reviewed_at": reviewed_at,
            "sent": sent,
        }
        self.append_record(record)

    def append_record(self, record: dict) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([record], columns=self.REQUIRED_COLUMNS)
        header = not self.csv_path.exists()
        df.to_csv(self.csv_path, mode="a", index=False, header=header)

    def list_sent_history(
        self,
        *,
        requester_institution: str,
        entity_id: str,
    ) -> list[DisclosureAuditRecord]:
        df = self.read_all()
        if df.empty:
            return []

        requester_norm = requester_institution.strip().upper()
        entity_norm = entity_id.strip().upper()

        filtered = df[
            (df["requester_institution"].astype(str).str.strip().str.upper() == requester_norm)
            & (df["entity_id"].astype(str).str.strip().str.upper() == entity_norm)
            & (
                df["sent"]
                .astype(str)
                .str.strip()
                .str.lower()
                .isin({"1", "true", "yes", "y"})
            )
        ]

        records: list[DisclosureAuditRecord] = []
        for _, row in filtered.iterrows():
            records.append(
                DisclosureAuditRecord(
                    review_id=str(row.get("review_id", "")),
                    case_id=str(row.get("case_id", "")),
                    requester_institution=str(row.get("requester_institution", "")),
                    responder_institution=str(row.get("responder_institution", "")),
                    entity_id=str(row.get("entity_id", "")),
                    request_message_id=str(row.get("request_message_id", "")),
                    response_message_id=str(row.get("response_message_id", "")),
                    in_reply_to=str(row.get("in_reply_to", "")),
                    match_type=str(row.get("match_type", "")),
                    summary=str(row.get("summary", "")),
                    allowed=_to_bool(row.get("allowed", False)),
                    blocked_layer=str(row.get("blocked_layer", "")),
                    reasons=str(row.get("reasons", "")),
                    layer_decisions_json=str(row.get("layer_decisions_json", "")),
                    reviewed_at=str(row.get("reviewed_at", "")),
                    sent=_to_bool(row.get("sent", False)),
                )
            )
        return records

    def read_all(self) -> pd.DataFrame:
        if not self.csv_path.exists():
            return pd.DataFrame(columns=self.REQUIRED_COLUMNS)
        return pd.read_csv(self.csv_path)


def _to_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}
