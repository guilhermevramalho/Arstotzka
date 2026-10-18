"""As regras antifraude. Cada regra é uma função pura:

    regra(pix, contexto) -> RuleHit | None

Não lê banco, não lê relógio: tudo o que ela sabe veio no PixData e no
RuleContext. Por isso cada uma é testada sozinha, valor por valor, nos
limites exatos dos parâmetros.

Quando uma regra tem várias faixas, devolve só a MAIS SEVERA (uma regra
conta no máximo uma vez por análise). Regra eliminatória devolve
hard_reject=True e 0 pontos: quem decide por ela é a precedência em
engine/decision.py, não a soma.
"""

import math
from typing import Callable, List, Optional

from engine import policy
from engine.geo import haversine_km
from engine.types import PixData, RuleContext, RuleHit

INTEGRIDADE = "INTEGRIDADE"
LIMITE = "LIMITE"
VELOCITY = "VELOCITY"
MONTANTE = "MONTANTE"
PERFIL = "PERFIL"
CONTRAPARTE = "CONTRAPARTE"


def brl(cents: int) -> str:
    """150000 -> 'R$ 1.500,00' (só para os textos de motivo)."""
    reais, centavos = divmod(int(cents), 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"


def _hard(code: str, family: str, reason: str, evidence: dict) -> RuleHit:
    return RuleHit(code, family, 0, reason, hard_reject=True, evidence=evidence)


def _points(code: str, family: str, points: int, reason: str, evidence: dict) -> RuleHit:
    return RuleHit(code, family, points, reason, hard_reject=False, evidence=evidence)


# ── INTEGRIDADE ──────────────────────────────────────────────────────

def int_01_same_account(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    same_owner = pix.source_document == pix.dest_document
    same_account = (
        pix.source_branch == pix.dest_branch
        and pix.source_account_number == pix.dest_account_number
    )
    if same_owner and same_account:
        return _hard(
            "INT_01", INTEGRIDADE,
            "Origem e destino são a mesma conta",
            {"branch": pix.source_branch, "account_number": pix.source_account_number},
        )
    return None


# ── LIMITE ───────────────────────────────────────────────────────────

def lim_01_amount_limit(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    cfg = policy.LIM_01[pix.source_person_type]
    evidence = {"amount": pix.amount, "person_type": pix.source_person_type}

    if pix.amount > cfg["reject_above"]:
        return _hard(
            "LIM_01", LIMITE,
            f"Valor acima do teto por transação {pix.source_person_type} ({brl(cfg['reject_above'])})",
            {**evidence, "reject_above": cfg["reject_above"]},
        )
    if pix.amount > cfg["attention_above"]:
        return _points(
            "LIM_01", LIMITE, cfg["points"],
            f"Valor acima do limite de atenção {pix.source_person_type} ({brl(cfg['attention_above'])})",
            {**evidence, "attention_above": cfg["attention_above"]},
        )
    return None


def lim_02_night_amount(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    if not pix.is_night:
        return None

    cfg = policy.LIM_02[pix.source_person_type]
    evidence = {"amount": pix.amount, "local_hour": pix.local_hour, "person_type": pix.source_person_type}

    if pix.amount > cfg["reject_above"]:
        return _hard(
            "LIM_02", LIMITE,
            f"Valor noturno acima do teto {pix.source_person_type} ({brl(cfg['reject_above'])})",
            {**evidence, "reject_above": cfg["reject_above"]},
        )
    if pix.amount > cfg["attention_above"]:
        return _points(
            "LIM_02", LIMITE, cfg["points"],
            f"Valor relevante em horário noturno (acima de {brl(cfg['attention_above'])})",
            {**evidence, "attention_above": cfg["attention_above"]},
        )
    return None


# ── VELOCITY ─────────────────────────────────────────────────────────

def _count_multiplier(pix: PixData) -> int:
    return policy.PJ_COUNT_MULTIPLIER if pix.source_person_type == "PJ" else 1


def vel_01_burst(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    cfg = policy.VEL_01
    multiplier = _count_multiplier(pix)
    reject_count = cfg["reject_count"] * multiplier
    attention_count = cfg["attention_count"] * multiplier

    if ctx.payer_attempts_5m >= reject_count:
        return _hard(
            "VEL_01", VELOCITY,
            f"{ctx.payer_attempts_5m} Pix do mesmo pagador em 5 minutos",
            {"attempts_5m": ctx.payer_attempts_5m, "reject_count": reject_count},
        )
    if ctx.payer_attempts_2m >= attention_count:
        return _points(
            "VEL_01", VELOCITY, cfg["points"],
            f"{ctx.payer_attempts_2m} Pix do mesmo pagador em 2 minutos",
            {"attempts_2m": ctx.payer_attempts_2m, "attention_count": attention_count},
        )
    return None


def vel_02_repeated_operation(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    cfg = policy.VEL_02

    # CORREÇÃO AQUI: >= 2 (a tentativa atual + 1 no histórico). 
    # Com >= 1, ele estava a bloquear o cliente no primeiro Pix!
    if ctx.identical_attempts_120s >= 2 and cfg.get("fatal_on_duplicate", True):
        return _hard(
            "VEL_02", VELOCITY,
            "Transação duplicada detectada em menos de 2 minutos (possível double-click ou retentativa de rede)",
            {"identical_120s": ctx.identical_attempts_120s}
        )

    if ctx.identical_attempts_10m >= cfg["reject_count"]:
        return _hard(
            "VEL_02", VELOCITY,
            f"{ctx.identical_attempts_10m} Pix idênticos (pagador, destino e valor) em 10 minutos",
            {"identical_10m": ctx.identical_attempts_10m, "reject_count": cfg["reject_count"]},
        )
    if ctx.identical_attempts_120s >= cfg["attention_count"]:
        return _points(
            "VEL_02", VELOCITY, cfg["points"],
            "Repetição do mesmo Pix (pagador, destino e valor) em até 120 segundos",
            {"identical_120s": ctx.identical_attempts_120s, "attention_count": cfg["attention_count"]},
        )
    return None


def vel_03_many_destinations(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    cfg = policy.VEL_03
    multiplier = _count_multiplier(pix)
    reject_count = cfg["reject_count"] * multiplier
    attention_count = cfg["attention_count"] * multiplier

    if ctx.distinct_destinations_10m >= reject_count:
        return _hard(
            "VEL_03", VELOCITY,
            f"{ctx.distinct_destinations_10m} destinatários distintos em 10 minutos",
            {"distinct_destinations_10m": ctx.distinct_destinations_10m, "reject_count": reject_count},
        )
    if ctx.distinct_destinations_10m >= attention_count:
        return _points(
            "VEL_03", VELOCITY, cfg["points"],
            f"{ctx.distinct_destinations_10m} destinatários distintos em 10 minutos",
            {"distinct_destinations_10m": ctx.distinct_destinations_10m, "attention_count": attention_count},
        )
    return None


# ── MONTANTE ─────────────────────────────────────────────────────────

def mon_01_accumulated_amount(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    cfg = policy.MON_01
    multiplier = policy.PJ_AMOUNT_MULTIPLIER if pix.source_person_type == "PJ" else 1
    min_count = cfg["min_count"]

    day_reject_above = cfg["day_reject_above"] * multiplier
    day_above = cfg["day_above"] * multiplier
    hour_above = cfg["hour_above"] * multiplier

    day_evidence = {"sum_24h": ctx.payer_moved_sum_24h, "count_24h": ctx.payer_moved_count_24h}
    hour_evidence = {"sum_1h": ctx.payer_moved_sum_1h, "count_1h": ctx.payer_moved_count_1h}

    if ctx.payer_moved_count_24h >= min_count:
        if ctx.payer_moved_sum_24h > day_reject_above:
            return _hard(
                "MON_01", MONTANTE,
                f"Soma de {brl(ctx.payer_moved_sum_24h)} em 24h acima do teto ({brl(day_reject_above)})",
                {**day_evidence, "reject_above": day_reject_above},
            )
        if ctx.payer_moved_sum_24h > day_above:
            return _points(
                "MON_01", MONTANTE, cfg["day_points"],
                f"Soma de {brl(ctx.payer_moved_sum_24h)} em 24h (acima de {brl(day_above)})",
                {**day_evidence, "above": day_above},
            )

    if ctx.payer_moved_count_1h >= min_count and ctx.payer_moved_sum_1h > hour_above:
        return _points(
            "MON_01", MONTANTE, cfg["hour_points"],
            f"Soma de {brl(ctx.payer_moved_sum_1h)} em 1h (acima de {brl(hour_above)})",
            {**hour_evidence, "above": hour_above},
        )
    return None


# ── PERFIL ───────────────────────────────────────────────────────────

def prf_01_amount_deviation(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    cfg = policy.PRF_01
    profile = ctx.profile

    if profile.tx_count_30d < cfg["min_history"] or pix.amount < cfg["min_amount"]:
        return None

    avg = profile.avg_ticket
    if avg <= 0: return None
    evidence = {
        "amount": pix.amount, "avg_ticket_30d": avg,
        "tx_count_30d": profile.tx_count_30d, "ratio": round(pix.amount / avg, 2),
    }

    if pix.amount > cfg["high_multiplier"] * avg:
        return _points(
            "PRF_01", PERFIL, cfg["high_points"],
            f"Valor mais de {cfg['high_multiplier']}x o ticket médio do cliente ({brl(avg)})",
            {**evidence, "multiplier": cfg["high_multiplier"]},
        )
    if pix.amount > cfg["attention_multiplier"] * avg:
        return _points(
            "PRF_01", PERFIL, cfg["attention_points"],
            f"Valor mais de {cfg['attention_multiplier']}x o ticket médio do cliente ({brl(avg)})",
            {**evidence, "multiplier": cfg["attention_multiplier"]},
        )
    return None


def prf_02_new_device(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    cfg = policy.PRF_02

    # Sem nenhum Pix aprovado antes não há "dispositivo de sempre" para
    # comparar: todo cliente novo estaria num dispositivo "novo".
    if ctx.approved_history_count == 0 or not ctx.device_is_new_for_payer:
        return None

    evidence = {"device_id": pix.device_id, "amount": pix.amount, "device_sum_24h": ctx.device_moved_sum_24h}

    if ctx.device_moved_sum_24h > cfg["day_amount_above"]:
        return _points(
            "PRF_02", PERFIL, cfg["day_points"],
            f"Dispositivo novo com {brl(ctx.device_moved_sum_24h)} em 24h (acima de {brl(cfg['day_amount_above'])})",
            {**evidence, "day_amount_above": cfg["day_amount_above"]},
        )
    if pix.amount > cfg["amount_above"]:
        return _points(
            "PRF_02", PERFIL, cfg["points"],
            f"Dispositivo novo com Pix acima de {brl(cfg['amount_above'])}",
            {**evidence, "amount_above": cfg["amount_above"]},
        )
    return None


def prf_03_shared_device(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    cfg = policy.PRF_03
    documents = ctx.device_distinct_documents_7d
    evidence = {"device_id": pix.device_id, "distinct_documents_7d": documents}

    # NOVO: Limiar eliminatório para Fazenda de Contas
    if documents >= cfg.get("fatal_documents", 4):
        return _hard(
            "PRF_03", PERFIL,
            f"Fazenda de contas: Dispositivo usado por {documents} titulares distintos em 7 dias",
            evidence,
        )
    if documents >= cfg["high_documents"]:
        return _points(
            "PRF_03", PERFIL, cfg["high_points"],
            f"Dispositivo usado por {documents} titulares distintos em 7 dias", evidence,
        )
    if documents >= cfg["attention_documents"]:
        return _points(
            "PRF_03", PERFIL, cfg["attention_points"],
            f"Dispositivo usado por {documents} titulares distintos em 7 dias", evidence,
        )
    return None


def prf_04_impossible_travel(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    cfg = policy.PRF_04
    last = ctx.last_approved_geo

    if not pix.has_geolocation or last is None:
        return None

    distance_km = haversine_km(last.latitude, last.longitude, pix.latitude, pix.longitude)
    if distance_km < cfg["min_distance_km"]:
        return None

    hours = (pix.transaction_date - last.transaction_date).total_seconds() / 3600
    speed_kmh = math.inf if hours <= 0 else distance_km / hours

    evidence = {
        "distance_km": round(distance_km, 1),
        "hours_since_last": round(hours, 3),
        "speed_kmh": None if math.isinf(speed_kmh) else round(speed_kmh, 1),
    }

    # NOVO: Account Takeover / Viagem Impossível absurda (VPN/GPS Fake)
    if speed_kmh > cfg.get("fatal_speed_kmh", 900):
        return _hard(
            "PRF_04", PERFIL,
            f"Viagem impossível detectada: {round(distance_km)} km desde o último Pix (acima de {cfg.get('fatal_speed_kmh', 900)} km/h)",
            evidence,
        )
    if speed_kmh > cfg["high_speed_kmh"]:
        return _points(
            "PRF_04", PERFIL, cfg["high_points"],
            f"Deslocamento incompatível: {round(distance_km)} km desde o último Pix (acima de {cfg['high_speed_kmh']} km/h)",
            evidence,
        )
    if speed_kmh > cfg["attention_speed_kmh"]:
        return _points(
            "PRF_04", PERFIL, cfg["attention_points"],
            f"Deslocamento suspeito: {round(distance_km)} km desde o último Pix (acima de {cfg['attention_speed_kmh']} km/h)",
            evidence,
        )
    return None


def prf_05_new_source_account(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    cfg = policy.PRF_05
    age = pix.source_account_age_seconds
    evidence = {"source_account_age_hours": round(age / 3600, 1), "amount": pix.amount}

    if age < cfg["brand_new_age"] and pix.amount > cfg["brand_new_amount_above"]:
        return _points(
            "PRF_05", PERFIL, cfg["brand_new_points"],
            f"Conta de origem com menos de 24h e Pix acima de {brl(cfg['brand_new_amount_above'])}", evidence,
        )
    if age < cfg["recent_age"] and pix.amount >= cfg["recent_min_amount"]:
        return _points(
            "PRF_05", PERFIL, cfg["recent_points"],
            f"Conta de origem com menos de 3 dias e Pix a partir de {brl(cfg['recent_min_amount'])}", evidence,
        )
    return None

def prf_06_timezone_spoofing(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    """Detecta tentativa de burlar as regras noturnas alterando o fuso horário do telemóvel."""
    if not pix.has_geolocation or not pix.transaction_date:
        return None
        
    cfg = policy.PRF_06
    
    # 1. Fuso horário que o telemóvel afirma ter (o fraudador altera isto)
    declared_tz = pix.transaction_date.utcoffset().total_seconds() / 3600
    
    # 2. Fuso horário geográfico real baseado no GPS (longitude / 15 graus)
    expected_tz = round(pix.longitude / 15)
    
    # 3. Se a divergência for absurda, é spoofing
    divergence = abs(expected_tz - declared_tz)
    
    if divergence >= cfg["max_tz_divergence_hours"]:
        return _hard(
            "PRF_06", PERFIL,
            f"Spoofing de GPS/Relógio: Fuso declarado (UTC{declared_tz:+.0f}) diverge fisicamente da coordenada GPS",
            {
                "longitude": round(pix.longitude, 2), 
                "declared_tz": declared_tz, 
                "expected_tz": expected_tz,
                "divergence": divergence
            }
        )
    return None

# ── CONTRAPARTE ──────────────────────────────────────────────────────

def ctp_01_new_destination_account(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    age = pix.dest_account_age_seconds

    for tier in policy.CTP_01:
        young_enough = age <= tier["max_age"] if tier["inclusive"] else age < tier["max_age"]
        if young_enough and pix.amount >= tier["min_amount"]:
            return _points(
                "CTP_01", CONTRAPARTE, tier["points"],
                f"Conta de destino aberta há {round(age / 3600, 1)}h recebendo {brl(pix.amount)}",
                {"dest_account_age_hours": round(age / 3600, 1), "amount": pix.amount,
                 "max_age_hours": tier["max_age"] // 3600, "min_amount": tier["min_amount"]},
            )
    return None


def ctp_02_receiving_concentration(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    cfg = policy.CTP_02

    if pix.dest_person_type != "PF":
        return None

    payers = ctx.dest_distinct_payers_1h
    evidence = {"distinct_payers_1h": payers, "dest_account_age_days": round(pix.dest_account_age_seconds / 86400, 1)}

    if payers >= cfg["high_payers"] and pix.dest_account_age_seconds < cfg["high_max_dest_age"]:
        return _points(
            "CTP_02", CONTRAPARTE, cfg["high_points"],
            f"Destino PF com menos de 30 dias recebeu de {payers} pagadores distintos em 1h", evidence,
        )
    if payers >= cfg["attention_payers"]:
        return _points(
            "CTP_02", CONTRAPARTE, cfg["attention_points"],
            f"Destino PF recebeu de {payers} pagadores distintos em 1h", evidence,
        )
    return None


def ctp_03_known_counterparty(pix: PixData, ctx: RuleContext) -> Optional[RuleHit]:
    cfg = policy.CTP_03

    if ctx.known_counterparty_count >= cfg["min_approved"]:
        return _points(
            "CTP_03", CONTRAPARTE, cfg["points"],
            "Destinatário conhecido: já recebeu Pix aprovado deste pagador há mais de 24h",
            {"approved_before_24h": ctx.known_counterparty_count},
        )
    return None


RULES: List[Callable[[PixData, RuleContext], Optional[RuleHit]]] = [
    int_01_same_account,
    lim_01_amount_limit,
    lim_02_night_amount,
    vel_01_burst,
    vel_02_repeated_operation,
    vel_03_many_destinations,
    mon_01_accumulated_amount,
    prf_01_amount_deviation,
    prf_02_new_device,
    prf_03_shared_device,
    prf_04_impossible_travel,
    prf_05_new_source_account,
    prf_06_timezone_spoofing,
    ctp_01_new_destination_account,
    ctp_02_receiving_concentration,
    ctp_03_known_counterparty,
]
