from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional
from utils import policy


def person_type_for(document_number: str) -> str:
    return "PF" if len(document_number) == 11 else "PJ"


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float
    transaction_date: datetime


@dataclass(frozen=True)
class PixData:
    pix_id: str
    amount: int
    transaction_date: datetime
    local_hour: int
    source_branch: str
    source_account_number: str
    source_document: str
    source_opening_date: datetime
    dest_participant: str
    dest_branch: str
    dest_account_number: str
    dest_document: str
    dest_opening_date: datetime
    device_id: str
    channel: str
    ip: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @property
    def source_person_type(self) -> str:
        return person_type_for(self.source_document)

    @property
    def dest_person_type(self) -> str:
        return person_type_for(self.dest_document)

    @property
    def dest_account_key(self) -> str:
        return f"{self.dest_participant}:{self.dest_branch}:{self.dest_account_number}"

    @property
    def has_geolocation(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def is_night(self) -> bool:
        return self.local_hour >= policy.NIGHT_START_HOUR or self.local_hour < policy.NIGHT_END_HOUR

    @property
    def source_account_age_seconds(self) -> float:
        return max(0.0, (self.transaction_date - self.source_opening_date).total_seconds())

    @property
    def dest_account_age_seconds(self) -> float:
        return max(0.0, (self.transaction_date - self.dest_opening_date).total_seconds())


@dataclass(frozen=True)
class HistorySnapshot:
    payer_attempts_2m: int = 0
    payer_attempts_5m: int = 0
    identical_attempts_120s: int = 0
    identical_attempts_10m: int = 0
    other_destinations_10m: int = 0
    payer_moved_sum_1h: int = 0
    payer_moved_count_1h: int = 0
    payer_moved_sum_24h: int = 0
    payer_moved_count_24h: int = 0
    profile_count_30d: int = 0
    profile_sum_30d: int = 0
    approved_history_count: int = 0
    device_used_in_approved: bool = False
    known_counterparty_count: int = 0
    last_approved_geo: Optional[GeoPoint] = None
    device_moved_sum_24h: int = 0
    device_other_documents_7d: int = 0
    dest_other_payers_1h: int = 0
    ml_history: Any = None


@dataclass(frozen=True)
class CustomerProfile:
    document_number: str
    person_type: str
    tx_count_30d: int
    total_amount_30d: int
    avg_ticket: Optional[int]


@dataclass(frozen=True)
class RuleContext:
    payer_attempts_2m: int
    payer_attempts_5m: int
    identical_attempts_120s: int
    identical_attempts_10m: int
    distinct_destinations_10m: int
    payer_moved_sum_1h: int
    payer_moved_count_1h: int
    payer_moved_sum_24h: int
    payer_moved_count_24h: int
    profile: CustomerProfile
    approved_history_count: int
    device_is_new_for_payer: bool
    device_moved_sum_24h: int
    device_distinct_documents_7d: int
    last_approved_geo: Optional[GeoPoint]
    dest_distinct_payers_1h: int
    known_counterparty_count: int
    ml_history: Any = None


def build_rule_context(pix: PixData, history: HistorySnapshot) -> RuleContext:
    profile_count = history.profile_count_30d
    avg_ticket = history.profile_sum_30d // profile_count if profile_count > 0 else None
    profile = CustomerProfile(
        document_number=pix.source_document,
        person_type=pix.source_person_type,
        tx_count_30d=profile_count,
        total_amount_30d=history.profile_sum_30d,
        avg_ticket=avg_ticket,
    )
    return RuleContext(
        payer_attempts_2m=history.payer_attempts_2m + 1,
        payer_attempts_5m=history.payer_attempts_5m + 1,
        identical_attempts_120s=history.identical_attempts_120s + 1,
        identical_attempts_10m=history.identical_attempts_10m + 1,
        distinct_destinations_10m=history.other_destinations_10m + 1,
        payer_moved_sum_1h=history.payer_moved_sum_1h + pix.amount,
        payer_moved_count_1h=history.payer_moved_count_1h + 1,
        payer_moved_sum_24h=history.payer_moved_sum_24h + pix.amount,
        payer_moved_count_24h=history.payer_moved_count_24h + 1,
        profile=profile,
        approved_history_count=history.approved_history_count,
        device_is_new_for_payer=not history.device_used_in_approved,
        device_moved_sum_24h=history.device_moved_sum_24h + pix.amount,
        device_distinct_documents_7d=history.device_other_documents_7d + 1,
        last_approved_geo=history.last_approved_geo,
        dest_distinct_payers_1h=history.dest_other_payers_1h + 1,
        known_counterparty_count=history.known_counterparty_count,
        ml_history=history.ml_history,
    )


@dataclass(frozen=True)
class RuleHit:
    rule_code: str
    family: str
    points: int
    reason: str
    hard_reject: bool = False
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    status: str
    score: int
    decided_by: str
    hits: List[RuleHit]

    @property
    def hard_reject(self) -> bool:
        return self.decided_by == "hard_rule"
