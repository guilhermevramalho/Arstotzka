from datetime import timedelta
from typing import Optional
import pandas as pd
from sqlalchemy import and_, func, select, text
from database import Context
from utils import policy
from utils.types import GeoPoint, HistorySnapshot, PixData
from models import FraudRuleHit, PixTransaction, RiskAnalysis

APPROVED = "approved"
MOVED_STATUSES = ("approved", "two_factor_required")
ML_HISTORY_SQL = text(
    "\n    SELECT pix_id, amount, transaction_date, local_hour,\n           source_branch, source_account_number, source_document, source_opening_date,\n           dest_participant, dest_branch, dest_account_number, dest_document, dest_opening_date,\n           device_id, channel, host(ip) AS ip, latitude, longitude\n    FROM pix_transaction\n    WHERE transaction_date < CAST(:t AS timestamptz)\n      AND (\n            (source_account_key = :src AND transaction_date > CAST(:t AS timestamptz) - interval '90 days')\n         OR (dest_account_key = :dst AND transaction_date > CAST(:t AS timestamptz) - interval '7 days')\n         OR (device_id = :dev AND transaction_date > CAST(:t AS timestamptz) - interval '7 days')\n         OR (ip = CAST(:ip AS inet) AND transaction_date > CAST(:t AS timestamptz) - interval '24 hours')\n      )\n    "
)


class PixTransactionRepository:

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def lock_payer(self, source_document: str) -> None:
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"payer:{source_document}"}
        )

    def get_by_pix_id(self, pix_id: str) -> Optional[PixTransaction]:
        return self.session.query(PixTransaction).filter(PixTransaction.pix_id == pix_id).first()

    def get_history_snapshot(self, pix: PixData) -> HistorySnapshot:
        t = pix.transaction_date

        def since(seconds: int):
            return PixTransaction.transaction_date > t - timedelta(seconds=seconds)

        status = RiskAnalysis.status
        approved = status == APPROVED
        moved = status.in_(MOVED_STATUSES)
        same_device = PixTransaction.device_id == pix.device_id
        same_dest = PixTransaction.dest_account_key == pix.dest_account_key

        def count_where(*conditions):
            return func.count().filter(and_(*conditions))

        def sum_where(*conditions):
            return func.coalesce(func.sum(PixTransaction.amount).filter(and_(*conditions)), 0)

        payer = self.session.execute(
            select(
                count_where(since(2 * policy.MINUTE)).label("attempts_2m"),
                count_where(since(5 * policy.MINUTE)).label("attempts_5m"),
                count_where(
                    since(policy.VEL_02["attention_window"]), same_dest, PixTransaction.amount == pix.amount
                ).label("identical_120s"),
                count_where(
                    since(policy.VEL_02["reject_window"]), same_dest, PixTransaction.amount == pix.amount
                ).label("identical_10m"),
                func.count(func.distinct(PixTransaction.dest_account_key))
                .filter(and_(since(policy.VEL_03["window"]), ~same_dest))
                .label("other_dests_10m"),
                sum_where(since(policy.HOUR), moved).label("moved_sum_1h"),
                count_where(since(policy.HOUR), moved).label("moved_count_1h"),
                sum_where(since(policy.DAY), moved).label("moved_sum_24h"),
                count_where(since(policy.DAY), moved).label("moved_count_24h"),
                count_where(since(policy.PROFILE_WINDOW), approved).label("profile_count_30d"),
                sum_where(since(policy.PROFILE_WINDOW), approved).label("profile_sum_30d"),
                count_where(approved).label("approved_history"),
                count_where(approved, same_device).label("device_approved"),
                sum_where(since(policy.DAY), moved, same_device).label("device_sum_24h"),
                count_where(
                    approved,
                    same_dest,
                    PixTransaction.transaction_date <= t - timedelta(seconds=policy.CTP_03["min_relationship_age"]),
                ).label("known_counterparty"),
            )
            .select_from(PixTransaction)
            .join(RiskAnalysis, RiskAnalysis.pix_transaction_id == PixTransaction.id)
            .where(PixTransaction.source_document == pix.source_document, PixTransaction.transaction_date <= t)
        ).one()
        last_geo_row = self.session.execute(
            select(PixTransaction.latitude, PixTransaction.longitude, PixTransaction.transaction_date)
            .join(RiskAnalysis, RiskAnalysis.pix_transaction_id == PixTransaction.id)
            .where(
                PixTransaction.source_document == pix.source_document,
                PixTransaction.transaction_date <= t,
                PixTransaction.latitude.is_not(None),
                approved,
            )
            .order_by(PixTransaction.transaction_date.desc())
            .limit(1)
        ).first()
        last_geo = None
        if last_geo_row is not None:
            last_geo = GeoPoint(
                float(last_geo_row.latitude), float(last_geo_row.longitude), last_geo_row.transaction_date
            )
        device_other_documents = self.session.execute(
            select(func.count(func.distinct(PixTransaction.source_document))).where(
                same_device,
                since(policy.PRF_03["window"]),
                PixTransaction.transaction_date <= t,
                PixTransaction.source_document != pix.source_document,
            )
        ).scalar_one()
        dest_other_payers = self.session.execute(
            select(func.count(func.distinct(PixTransaction.source_document))).where(
                same_dest,
                since(policy.CTP_02["window"]),
                PixTransaction.transaction_date <= t,
                PixTransaction.source_document != pix.source_document,
            )
        ).scalar_one()
        return HistorySnapshot(
            payer_attempts_2m=payer.attempts_2m,
            payer_attempts_5m=payer.attempts_5m,
            identical_attempts_120s=payer.identical_120s,
            identical_attempts_10m=payer.identical_10m,
            other_destinations_10m=payer.other_dests_10m,
            payer_moved_sum_1h=int(payer.moved_sum_1h),
            payer_moved_count_1h=payer.moved_count_1h,
            payer_moved_sum_24h=int(payer.moved_sum_24h),
            payer_moved_count_24h=payer.moved_count_24h,
            profile_count_30d=payer.profile_count_30d,
            profile_sum_30d=int(payer.profile_sum_30d),
            approved_history_count=payer.approved_history,
            device_used_in_approved=payer.device_approved > 0,
            known_counterparty_count=payer.known_counterparty,
            last_approved_geo=last_geo,
            device_moved_sum_24h=int(payer.device_sum_24h),
            device_other_documents_7d=device_other_documents,
            dest_other_payers_1h=dest_other_payers,
            ml_history=self.get_ml_history(pix),
        )

    def get_ml_history(self, pix: PixData) -> pd.DataFrame:
        params = {
            "t": pix.transaction_date,
            "src": f"{pix.source_branch}:{pix.source_account_number}",
            "dst": pix.dest_account_key,
            "dev": pix.device_id,
            "ip": pix.ip,
        }
        rows = self.session.execute(ML_HISTORY_SQL, params).mappings().all()
        return pd.DataFrame([dict(row) for row in rows])

    def create_transaction(self, pix: PixData, payload_hash: str, raw_payload: dict) -> PixTransaction:
        transaction = PixTransaction(
            pix_id=pix.pix_id,
            payload_hash=payload_hash,
            raw_payload=raw_payload,
            amount=pix.amount,
            transaction_date=pix.transaction_date,
            local_hour=pix.local_hour,
            source_branch=pix.source_branch,
            source_account_number=pix.source_account_number,
            source_document=pix.source_document,
            source_opening_date=pix.source_opening_date,
            dest_participant=pix.dest_participant,
            dest_branch=pix.dest_branch,
            dest_account_number=pix.dest_account_number,
            dest_document=pix.dest_document,
            dest_opening_date=pix.dest_opening_date,
            device_id=pix.device_id,
            channel=pix.channel,
            ip=pix.ip,
            latitude=pix.latitude,
            longitude=pix.longitude,
        )
        self.session.add(transaction)
        self.session.flush()
        return transaction

    def create_analysis(self, transaction: PixTransaction, analysis_key: str, decision, metadata: dict) -> RiskAnalysis:
        analysis = RiskAnalysis(
            pix_transaction_id=transaction.id,
            analysis_key=analysis_key,
            status=decision.status,
            score=decision.score,
            decided_by=decision.decided_by,
            rules_version=policy.POLICY_VERSION,
            analysis_metadata=metadata,
        )
        self.session.add(analysis)
        self.session.flush()
        for hit in decision.hits:
            self.session.add(
                FraudRuleHit(
                    risk_analysis_id=analysis.id,
                    rule_code=hit.rule_code,
                    rule_family=hit.family,
                    points=hit.points,
                    is_hard_reject=hit.hard_reject,
                    reason=hit.reason,
                    evidence=hit.evidence,
                )
            )
        return analysis
