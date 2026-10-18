import math
from typing import Tuple, List, Optional
from uuid import uuid4
from sqlalchemy.exc import IntegrityError
from controllers.base_controller import BaseController
from dtos import PixAnalysisDTO
from errors import ConflictingPixId, NotFoundPixTransaction
from models import PixTransaction
from repositories import PixTransactionRepository
from utils.pix_payload import payload_hash, to_pix_data
from utils import policy
from utils.geo import haversine_km
from utils.ml_model import score_pix
from utils.types import PixData, RuleContext, RuleHit, Decision, HistorySnapshot, build_rule_context

INTEGRIDADE = "INTEGRIDADE"
LIMITE = "LIMITE"
VELOCITY = "VELOCITY"
MONTANTE = "MONTANTE"
PERFIL = "PERFIL"
CONTRAPARTE = "CONTRAPARTE"


class PixTransactionController(BaseController):

    def __init__(self) -> None:
        super().__init__(__name__)
        self.pix_repository = PixTransactionRepository(self.context)

    def analyze(self, payload: dict) -> Tuple[dict, bool]:
        pix = to_pix_data(payload)
        current_hash = payload_hash(payload)
        self.pix_repository.lock_payer(pix.source_document)
        existing = self.pix_repository.get_by_pix_id(pix.pix_id)
        if existing is not None:
            return (self._replay_or_conflict(existing, current_hash, pix.pix_id), False)
        history = self.pix_repository.get_history_snapshot(pix)
        decision = self.evaluate(pix, history)
        metadata = self.build_metadata(decision)
        self.logger.info(
            f"Pix {pix.pix_id}: {decision.status} (score {decision.score}, regras {[hit.rule_code for hit in decision.hits]})"
        )
        try:
            transaction = self.pix_repository.create_transaction(pix, current_hash, payload)
            analysis = self.pix_repository.create_analysis(transaction, str(uuid4()), decision, metadata)
            response = PixAnalysisDTO.obj_to_dict(analysis)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.pix_repository.get_by_pix_id(pix.pix_id)
            if existing is None:
                raise
            return (self._replay_or_conflict(existing, current_hash, pix.pix_id), False)
        return (response, True)

    def get_by_pix_id(self, pix_id: str) -> dict:
        transaction = self.pix_repository.get_by_pix_id(pix_id)
        if transaction is None or transaction.analysis is None:
            raise NotFoundPixTransaction(pix_id)
        return PixAnalysisDTO.obj_to_dict(transaction.analysis)

    def _replay_or_conflict(self, existing: PixTransaction, current_hash: str, pix_id: str) -> dict:
        if existing.payload_hash != current_hash:
            raise ConflictingPixId(pix_id)
        return PixAnalysisDTO.obj_to_dict(existing.analysis)

    def evaluate(self, pix: PixData, history: HistorySnapshot) -> Decision:
        context = build_rule_context(pix, history)
        hits = []
        rules = [
            self._int_01_same_account,
            self._lim_01_amount_limit,
            self._lim_02_night_amount,
            self._vel_01_burst,
            self._vel_02_repeated_operation,
            self._vel_03_many_destinations,
            self._mon_01_accumulated_amount,
            self._prf_01_amount_deviation,
            self._prf_02_new_device,
            self._prf_03_shared_device,
            self._prf_04_impossible_travel,
            self._prf_05_new_source_account,
            self._prf_06_timezone_spoofing,
            self._prf_07_behavioral_score,
            self._ctp_01_new_destination_account,
            self._ctp_02_receiving_concentration,
            self._ctp_03_known_counterparty,
        ]
        for rule in rules:
            hit = rule(pix, context)
            if hit is not None:
                hits.append(hit)
        return self._decide(hits)

    def _decide(self, hits: List[RuleHit]) -> Decision:
        score = max(0, sum((hit.points for hit in hits)))
        if any((hit.hard_reject for hit in hits)):
            return Decision(status="rejected", score=score, decided_by="hard_rule", hits=hits)
        if score >= policy.REJECT_FROM_SCORE:
            status = "rejected"
        elif score >= policy.TWO_FACTOR_FROM_SCORE:
            status = "two_factor_required"
        else:
            status = "approved"
        return Decision(status=status, score=score, decided_by="score", hits=hits)

    def build_metadata(self, decision: Decision) -> dict:
        return {
            "engine_version": policy.ENGINE_VERSION,
            "policy_version": policy.POLICY_VERSION,
            "score": decision.score,
            "decision": decision.status,
            "decided_by": decision.decided_by,
            "hard_reject": decision.hard_reject,
            "triggered_rules": [
                {
                    "rule_id": hit.rule_code,
                    "family": hit.family,
                    "points": hit.points,
                    "hard_reject": hit.hard_reject,
                    "reason": hit.reason,
                    "evidence": hit.evidence,
                }
                for hit in decision.hits
            ],
        }

    def _int_01_same_account(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        same_owner = pix.source_document == pix.dest_document
        same_account = pix.source_branch == pix.dest_branch and pix.source_account_number == pix.dest_account_number
        if same_owner and same_account:
            return self._hard(
                "INT_01",
                INTEGRIDADE,
                "Origem e destino são a mesma conta",
                {"branch": pix.source_branch, "account_number": pix.source_account_number},
            )
        return None

    def _lim_01_amount_limit(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        cfg = policy.LIM_01[pix.source_person_type]
        evidence = {"amount": pix.amount, "person_type": pix.source_person_type}
        if pix.amount > cfg["reject_above"]:
            return self._hard(
                "LIM_01",
                LIMITE,
                f"Valor acima do teto {pix.source_person_type} ({self._brl(cfg['reject_above'])})",
                {**evidence, "reject_above": cfg["reject_above"]},
            )
        if pix.amount > cfg["attention_above"]:
            return self._points(
                "LIM_01",
                LIMITE,
                cfg["points"],
                f"Valor acima da atenção {pix.source_person_type} ({self._brl(cfg['attention_above'])})",
                {**evidence, "attention_above": cfg["attention_above"]},
            )
        return None

    def _lim_02_night_amount(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        if not pix.is_night:
            return None
        cfg = policy.LIM_02[pix.source_person_type]
        evidence = {"amount": pix.amount, "local_hour": pix.local_hour, "person_type": pix.source_person_type}
        if pix.amount > cfg["reject_above"]:
            return self._hard(
                "LIM_02",
                LIMITE,
                f"Valor noturno acima do teto {pix.source_person_type} ({self._brl(cfg['reject_above'])})",
                {**evidence, "reject_above": cfg["reject_above"]},
            )
        if pix.amount > cfg["attention_above"]:
            return self._points(
                "LIM_02",
                LIMITE,
                cfg["points"],
                f"Valor relevante em horário noturno (acima de {self._brl(cfg['attention_above'])})",
                {**evidence, "attention_above": cfg["attention_above"]},
            )
        return None

    def _vel_01_burst(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        cfg = policy.VEL_01
        multiplier = policy.PJ_COUNT_MULTIPLIER if pix.source_person_type == "PJ" else 1
        reject_count = cfg["reject_count"] * multiplier
        attention_count = cfg["attention_count"] * multiplier
        if ctx.payer_attempts_5m >= reject_count:
            return self._hard(
                "VEL_01",
                VELOCITY,
                f"{ctx.payer_attempts_5m} Pix do mesmo pagador em 5 min",
                {"attempts_5m": ctx.payer_attempts_5m, "reject_count": reject_count},
            )
        if ctx.payer_attempts_2m >= attention_count:
            return self._points(
                "VEL_01",
                VELOCITY,
                cfg["points"],
                f"{ctx.payer_attempts_2m} Pix do mesmo pagador em 2 min",
                {"attempts_2m": ctx.payer_attempts_2m, "attention_count": attention_count},
            )
        return None

    def _vel_02_repeated_operation(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        cfg = policy.VEL_02
        if ctx.identical_attempts_120s >= 2 and cfg.get("fatal_on_duplicate", True):
            return self._hard(
                "VEL_02",
                VELOCITY,
                "Transação duplicada detectada em menos de 2 minutos",
                {"identical_120s": ctx.identical_attempts_120s},
            )
        if ctx.identical_attempts_10m >= cfg["reject_count"]:
            return self._hard(
                "VEL_02",
                VELOCITY,
                f"{ctx.identical_attempts_10m} Pix idênticos em 10 min",
                {"identical_10m": ctx.identical_attempts_10m, "reject_count": cfg["reject_count"]},
            )
        if ctx.identical_attempts_120s >= cfg["attention_count"]:
            return self._points(
                "VEL_02",
                VELOCITY,
                cfg["points"],
                "Repetição do mesmo Pix em até 120s",
                {"identical_120s": ctx.identical_attempts_120s, "attention_count": cfg["attention_count"]},
            )
        return None

    def _vel_03_many_destinations(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        cfg = policy.VEL_03
        multiplier = policy.PJ_COUNT_MULTIPLIER if pix.source_person_type == "PJ" else 1
        reject_count = cfg["reject_count"] * multiplier
        attention_count = cfg["attention_count"] * multiplier
        if ctx.distinct_destinations_10m >= reject_count:
            return self._hard(
                "VEL_03",
                VELOCITY,
                f"{ctx.distinct_destinations_10m} destinos em 10 min",
                {"distinct_destinations_10m": ctx.distinct_destinations_10m, "reject_count": reject_count},
            )
        if ctx.distinct_destinations_10m >= attention_count:
            return self._points(
                "VEL_03",
                VELOCITY,
                cfg["points"],
                f"{ctx.distinct_destinations_10m} destinos em 10 min",
                {"distinct_destinations_10m": ctx.distinct_destinations_10m, "attention_count": attention_count},
            )
        return None

    def _mon_01_accumulated_amount(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        cfg = policy.MON_01
        multiplier = policy.PJ_AMOUNT_MULTIPLIER if pix.source_person_type == "PJ" else 1
        min_count = cfg["min_count"]
        day_reject = cfg["day_reject_above"] * multiplier
        day_above = cfg["day_above"] * multiplier
        hour_above = cfg["hour_above"] * multiplier
        day_evidence = {"sum_24h": ctx.payer_moved_sum_24h, "count_24h": ctx.payer_moved_count_24h}
        if ctx.payer_moved_count_24h >= min_count:
            if ctx.payer_moved_sum_24h > day_reject:
                return self._hard(
                    "MON_01",
                    MONTANTE,
                    f"Soma de {self._brl(ctx.payer_moved_sum_24h)} em 24h acima do teto",
                    {**day_evidence, "reject_above": day_reject},
                )
            if ctx.payer_moved_sum_24h > day_above:
                return self._points(
                    "MON_01",
                    MONTANTE,
                    cfg["day_points"],
                    f"Soma de {self._brl(ctx.payer_moved_sum_24h)} em 24h",
                    {**day_evidence, "above": day_above},
                )
        if ctx.payer_moved_count_1h >= min_count and ctx.payer_moved_sum_1h > hour_above:
            return self._points(
                "MON_01",
                MONTANTE,
                cfg["hour_points"],
                f"Soma de {self._brl(ctx.payer_moved_sum_1h)} em 1h",
                {"sum_1h": ctx.payer_moved_sum_1h, "count_1h": ctx.payer_moved_count_1h, "above": hour_above},
            )
        return None

    def _prf_01_amount_deviation(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        cfg = policy.PRF_01
        if (
            ctx.profile.tx_count_30d < cfg["min_history"]
            or pix.amount < cfg["min_amount"]
            or ctx.profile.avg_ticket is None
            or (ctx.profile.avg_ticket <= 0)
        ):
            return None
        avg = ctx.profile.avg_ticket
        evidence = {"amount": pix.amount, "avg_ticket_30d": avg, "tx_count_30d": ctx.profile.tx_count_30d}
        if pix.amount > cfg["high_multiplier"] * avg:
            return self._points(
                "PRF_01", PERFIL, cfg["high_points"], f"Valor mais de {cfg['high_multiplier']}x o médio", {**evidence}
            )
        if pix.amount > cfg["attention_multiplier"] * avg:
            return self._points(
                "PRF_01",
                PERFIL,
                cfg["attention_points"],
                f"Valor mais de {cfg['attention_multiplier']}x o médio",
                {**evidence},
            )
        return None

    def _prf_02_new_device(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        if ctx.approved_history_count == 0 or not ctx.device_is_new_for_payer:
            return None
        cfg = policy.PRF_02
        evidence = {"device_id": pix.device_id, "amount": pix.amount, "device_sum_24h": ctx.device_moved_sum_24h}
        if ctx.device_moved_sum_24h > cfg["day_amount_above"]:
            return self._points(
                "PRF_02",
                PERFIL,
                cfg["day_points"],
                f"Device novo com {self._brl(ctx.device_moved_sum_24h)} em 24h",
                evidence,
            )
        if pix.amount > cfg["amount_above"]:
            return self._points(
                "PRF_02", PERFIL, cfg["points"], f"Device novo acima de {self._brl(cfg['amount_above'])}", evidence
            )
        return None

    def _prf_03_shared_device(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        cfg = policy.PRF_03
        docs = ctx.device_distinct_documents_7d
        evidence = {"device_id": pix.device_id, "distinct_documents_7d": docs}
        if docs >= cfg.get("fatal_documents", 4):
            return self._hard("PRF_03", PERFIL, f"Fazenda: Device usado por {docs} CPFs em 7 dias", evidence)
        if docs >= cfg["high_documents"]:
            return self._points(
                "PRF_03", PERFIL, cfg["high_points"], f"Device usado por {docs} CPFs em 7 dias", evidence
            )
        if docs >= cfg["attention_documents"]:
            return self._points(
                "PRF_03", PERFIL, cfg["attention_points"], f"Device usado por {docs} CPFs em 7 dias", evidence
            )
        return None

    def _prf_04_impossible_travel(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        cfg = policy.PRF_04
        last = ctx.last_approved_geo
        if not pix.has_geolocation or last is None:
            return None
        distance_km = haversine_km(last.latitude, last.longitude, pix.latitude, pix.longitude)
        if distance_km < cfg["min_distance_km"]:
            return None
        hours = (pix.transaction_date - last.transaction_date).total_seconds() / 3600
        speed = math.inf if hours <= 0 else distance_km / hours
        speed_str = "+inf" if math.isinf(speed) else str(round(speed))
        evidence = {"distance_km": round(distance_km, 1), "speed_kmh": None if math.isinf(speed) else round(speed, 1)}
        if speed > cfg.get("fatal_speed_kmh", 900):
            return self._hard("PRF_04", PERFIL, f"Viagem impossível: {speed_str} km/h", evidence)
        if speed > cfg["high_speed_kmh"]:
            return self._points(
                "PRF_04", PERFIL, cfg["high_points"], f"Deslocamento incompatível: {speed_str} km/h", evidence
            )
        if speed > cfg["attention_speed_kmh"]:
            return self._points(
                "PRF_04", PERFIL, cfg["attention_points"], f"Deslocamento suspeito: {speed_str} km/h", evidence
            )
        return None

    def _prf_05_new_source_account(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        cfg = policy.PRF_05
        age = pix.source_account_age_seconds
        evidence = {"source_account_age_hours": round(age / 3600, 1), "amount": pix.amount}
        if age < cfg["brand_new_age"] and pix.amount > cfg["brand_new_amount_above"]:
            return self._points("PRF_05", PERFIL, cfg["brand_new_points"], "Conta < 24h e Pix alto", evidence)
        if age < cfg["recent_age"] and pix.amount >= cfg["recent_min_amount"]:
            return self._points("PRF_05", PERFIL, cfg["recent_points"], "Conta < 3 dias e Pix alto", evidence)
        return None

    def _prf_06_timezone_spoofing(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        if not pix.has_geolocation or not pix.transaction_date:
            return None
        cfg = policy.PRF_06
        declared_tz = pix.transaction_date.utcoffset().total_seconds() / 3600
        expected_tz = round(pix.longitude / 15)
        divergence = abs(expected_tz - declared_tz)
        if divergence >= cfg["max_tz_divergence_hours"]:
            return self._hard(
                "PRF_06",
                PERFIL,
                f"Spoofing: Fuso UTC{declared_tz:+.0f} diverge do GPS",
                {"declared_tz": declared_tz, "expected_tz": expected_tz, "divergence": divergence},
            )
        return None

    def _prf_07_behavioral_score(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        if ctx.ml_history is None:
            return None
        result = score_pix(pix, ctx.ml_history)
        if result is None:
            return None
        cfg = policy.PRF_07
        cold_start = (
            result["payer_history_count"] == 0
            and result["source_account_age_days"] >= cfg["cold_start_min_account_age_days"]
        )
        if cold_start:
            return None
        thresholds = result["thresholds"]
        if result["score"] >= thresholds["reject"]:
            points, level, threshold = (cfg["high_points"], "alto", thresholds["reject"])
        elif result["score"] >= thresholds["two_factor"]:
            points, level, threshold = (cfg["medium_points"], "médio", thresholds["two_factor"])
        else:
            return None
        detail = (
            "; ".join((factor["text"] for factor in result["factors"]))
            or "combinação de sinais fora do padrão do pagador"
        )
        evidence = {
            "model_version": result["model_version"],
            "score": result["score"],
            "threshold": threshold,
            "factors": result["factors"],
        }
        return self._points("PRF_07", PERFIL, points, f"Modelo comportamental indica risco {level}: {detail}", evidence)

    def _ctp_01_new_destination_account(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        age = pix.dest_account_age_seconds
        for tier in policy.CTP_01:
            young = age <= tier["max_age"] if tier["inclusive"] else age < tier["max_age"]
            if young and pix.amount >= tier["min_amount"]:
                return self._points(
                    "CTP_01",
                    CONTRAPARTE,
                    tier["points"],
                    f"Destino novo ({round(age / 3600, 1)}h) com Pix alto",
                    {"dest_age_hours": round(age / 3600, 1), "amount": pix.amount},
                )
        return None

    def _ctp_02_receiving_concentration(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        cfg = policy.CTP_02
        if pix.dest_person_type != "PF":
            return None
        payers = ctx.dest_distinct_payers_1h
        evidence = {"distinct_payers_1h": payers}
        if payers >= cfg["high_payers"] and pix.dest_account_age_seconds < cfg["high_max_dest_age"]:
            return self._points(
                "CTP_02", CONTRAPARTE, cfg["high_points"], f"Destino PF novo com {payers} pagadores em 1h", evidence
            )
        if payers >= cfg["attention_payers"]:
            return self._points(
                "CTP_02", CONTRAPARTE, cfg["attention_points"], f"Destino PF com {payers} pagadores em 1h", evidence
            )
        return None

    def _ctp_03_known_counterparty(self, pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
        if ctx.known_counterparty_count >= policy.CTP_03["min_approved"]:
            return self._points(
                "CTP_03",
                CONTRAPARTE,
                policy.CTP_03["points"],
                "Destinatário conhecido > 24h",
                {"approved_before_24h": ctx.known_counterparty_count},
            )
        return None

    def _brl(self, cents: int) -> str:
        reais, centavos = divmod(int(cents), 100)
        return f"R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"

    def _hard(self, code: str, family: str, reason: str, evidence: dict) -> RuleHit:
        return RuleHit(code, family, 0, reason, hard_reject=True, evidence=evidence)

    def _points(self, code: str, family: str, points: int, reason: str, evidence: dict) -> RuleHit:
        return RuleHit(code, family, points, reason, hard_reject=False, evidence=evidence)
