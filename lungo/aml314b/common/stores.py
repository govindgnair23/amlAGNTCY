from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from aml314b.common.channeling import InvestigationType, normalize_investigation_type
from aml314b.common.schemas import B314Request, B314Response, TimeWindow


@dataclass(frozen=True)
class ActiveCase:
    case_id: str
    investigation_type: InvestigationType
    entity_id: str
    entity_name: str
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
        "investigation_type",
        "entity_id",
        "entity_name",
        "counterparty_id",
        "time_window_start",
        "time_window_end",
        "status",
    }

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)
        self._df = self._load_dataframe()

    def list_active_cases(
        self,
        investigation_type: str | InvestigationType | None = None,
    ) -> list[ActiveCase]:
        active_df = self._df[self._df["status"].str.upper() == "ACTIVE"].copy()
        if active_df.empty:
            active_df = self._df.copy()
        if investigation_type is not None:
            active_df = active_df[
                active_df["investigation_type"]
                == normalize_investigation_type(investigation_type).value
            ]
        return [self._row_to_case(row) for _, row in active_df.iterrows()]

    def get_case(
        self,
        case_id: str,
        investigation_type: str | InvestigationType | None = None,
    ) -> ActiveCase:
        matches = self._df[self._df["case_id"] == case_id]
        if investigation_type is not None:
            matches = matches[
                matches["investigation_type"]
                == normalize_investigation_type(investigation_type).value
            ]
        if matches.empty:
            if investigation_type is None:
                raise KeyError(f"No active investigation found for case_id={case_id}")
            normalized = normalize_investigation_type(investigation_type).value
            raise KeyError(
                "No active investigation found for "
                f"case_id={case_id} investigation_type={normalized}"
            )
        if len(matches.index) > 1 and investigation_type is None:
            raise KeyError(
                "Multiple active investigations found for "
                f"case_id={case_id}; investigation_type is required."
            )
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
        df["investigation_type"] = df["investigation_type"].map(
            lambda value: normalize_investigation_type(str(value)).value
        )
        return df

    def _row_to_case(self, row: pd.Series) -> ActiveCase:
        activity_summary = None
        if "case_summary" in row:
            value = row.get("case_summary")
            if pd.notna(value):
                activity_summary = str(value)
        return ActiveCase(
            case_id=str(row["case_id"]),
            investigation_type=normalize_investigation_type(str(row["investigation_type"])),
            entity_id=str(row["entity_id"]),
            entity_name=str(row["entity_name"]),
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

    def list_routes(
        self, transport: str, institution_ids: Iterable[str] | None = None
    ) -> list[DirectoryRoute]:
        transport_key = transport.strip().upper()
        allowed_ids = (
            {institution_id.strip().upper() for institution_id in institution_ids}
            if institution_ids is not None
            else None
        )
        routes = [
            route
            for route in self._routes.values()
            if route.transport == transport_key and route.enabled
        ]
        if allowed_ids is not None:
            routes = [route for route in routes if route.institution_id.upper() in allowed_ids]
        return sorted(routes, key=lambda route: route.institution_id)

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
            routes[(institution_id, transport)] = DirectoryRoute(
                institution_id=str(row["institution_id"]),
                transport=transport,
                endpoint=str(row["endpoint"]),
                enabled=bool(row["enabled"]),
            )
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

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)
        self._df = self._load_dataframe()

    def get_context(self, entity_id: str, case_id: str | None = None) -> str | None:
        matches = self._df[self._df["entity_id"] == entity_id]
        if case_id and "case_id" in self._df.columns:
            case_matches = matches[matches["case_id"].fillna("").astype(str) == case_id]
            if not case_matches.empty:
                return str(case_matches.iloc[0]["summary"])
        if matches.empty:
            return None
        return str(matches.iloc[0]["summary"])

    def _load_dataframe(self) -> pd.DataFrame:
        df = pd.read_csv(self.csv_path)
        missing = self.REQUIRED_COLUMNS.difference(df.columns)
        if missing:
            raise ValueError(
                "CuratedInvestigativeContextStore missing required columns: "
                f"{sorted(missing)}"
            )
        df["entity_id"] = df["entity_id"].astype(str)
        df["summary"] = df["summary"].fillna("").astype(str)
        return df


class LaneSubscriptionStore:
    REQUIRED_COLUMNS = {"investigation_type"}

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)
        self._df = self._load_dataframe()
        self._supported_investigation_types = tuple(
            sorted(
                {
                    normalize_investigation_type(str(value))
                    for value in self._df["investigation_type"].tolist()
                },
                key=lambda investigation_type: investigation_type.value,
            )
        )

    def list_supported_investigation_types(self) -> list[InvestigationType]:
        return list(self._supported_investigation_types)

    def supports(self, investigation_type: str | InvestigationType) -> bool:
        normalized = normalize_investigation_type(investigation_type)
        return normalized in self._supported_investigation_types

    def _load_dataframe(self) -> pd.DataFrame:
        df = pd.read_csv(self.csv_path)
        missing = self.REQUIRED_COLUMNS.difference(df.columns)
        if missing:
            raise ValueError(
                f"LaneSubscriptionStore missing required columns: {sorted(missing)}"
            )
        df["investigation_type"] = df["investigation_type"].map(
            lambda value: normalize_investigation_type(str(value)).value
        )
        return df


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
