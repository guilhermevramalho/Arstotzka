"""Catálogo de cenários do motor — a fonte única de verdade.

Cada cenário descreve um Pix e o histórico que existia antes dele, e diz
qual decisão e quais regras o motor TEM que produzir. O mesmo catálogo:

  • roda como teste (tests/unit/test_scenarios.py), e
  • gera a documentação (python scripts/gerar_cenarios.py → docs/cenarios.md).

Assim o documento nunca descreve uma regra diferente da que o código roda.

Convenções:
  • Pix base: PF → PF, quinta 15/10/2026 às 14h (-03:00), R$ 100,00,
    contas abertas há anos, dispositivo já usado pelo cliente.
  • Histórico base: cliente com 10 Pix aprovados (mais antigos que 30
    dias), nada recente. Cada cenário só muda o que interessa a ele.
  • Valores em REAIS nos cenários (convertidos para centavos aqui).
  • expected: {"REGRA": pontos} ou {"REGRA": HARD} para eliminatória.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple, Union

from engine.types import GeoPoint, HistorySnapshot, PixData

HARD = "HARD"
APPROVED = "approved"
TWO_FA = "two_factor_required"
REJECTED = "rejected"

BRT = timezone(timedelta(hours=-3))
BASE_DATE = datetime(2026, 10, 15, 14, 0, tzinfo=BRT)

CPF_PAYER = "12345678909"
CPF_RECEIVER = "98765432100"
CNPJ_PAYER = "11222333000181"
CNPJ_RECEIVER = "44555666000199"

SAO_PAULO = (-23.5505, -46.6333)
CAMPINAS = (-22.9099, -47.0626)
RIO = (-22.9068, -43.1729)
RECIFE = (-8.0476, -34.8770)

LONG_AGO = timedelta(days=900)


def cents(reais: float) -> int:
    return int(round(reais * 100))


def make_pix(
    amount: float = 100.00,
    hour: int = 14,
    minute: int = 0,
    tz: timezone = BRT,
    payer: str = "PF",
    receiver: str = "PF",
    source_age: timedelta = LONG_AGO,
    dest_age: timedelta = LONG_AGO,
    geo: Optional[Tuple[float, float]] = SAO_PAULO,
    same_account: bool = False,
    same_owner: bool = False,
) -> PixData:
    transaction_date = datetime(2026, 10, 15, hour, minute, tzinfo=tz)
    source_document = CPF_PAYER if payer == "PF" else CNPJ_PAYER
    if same_owner or same_account:
        dest_document = source_document
    else:
        dest_document = CPF_RECEIVER if receiver == "PF" else CNPJ_RECEIVER

    return PixData(
        pix_id="pix-catalogo",
        amount=cents(amount),
        transaction_date=transaction_date,
        local_hour=transaction_date.hour,
        source_branch="0001",
        source_account_number="88213",
        source_document=source_document,
        source_opening_date=transaction_date - source_age,
        dest_participant="60701190",
        dest_branch="0001" if same_account else "3675",
        dest_account_number="88213" if same_account else "10442",
        dest_document=dest_document,
        dest_opening_date=transaction_date - dest_age,
        device_id="dvc-celular-do-cliente",
        channel="app",
        ip="198.51.100.23",
        latitude=geo[0] if geo else None,
        longitude=geo[1] if geo else None,
    )


def make_history(**overrides) -> HistorySnapshot:
    base = dict(approved_history_count=10, device_used_in_approved=True)
    base.update(overrides)
    for key in ("payer_moved_sum_1h", "payer_moved_sum_24h", "profile_sum_30d", "device_moved_sum_24h"):
        if key in base:
            base[key] = cents(base[key])
    return HistorySnapshot(**base)


def geo_before(point: Tuple[float, float], hours_before: float) -> GeoPoint:
    return GeoPoint(point[0], point[1], BASE_DATE - timedelta(hours=hours_before))


@dataclass
class Scenario:
    id: str
    group: str
    title: str
    pix: dict = field(default_factory=dict)
    history: dict = field(default_factory=dict)
    expected_status: str = APPROVED
    expected: Dict[str, Union[int, str]] = field(default_factory=dict)
    note: str = ""

    def build(self):
        return make_pix(**self.pix), make_history(**self.history)


S = Scenario
D = timedelta(days=1)
H = timedelta(hours=1)

CATALOG = [
    # ─── Base ────────────────────────────────────────────────────────
    S("BASE-01", "Base", "Pix comum: PF, 14h, R$ 100, dispositivo e contas antigas", {}, {}, APPROVED, {}),
    S("BASE-02", "Base", "Primeiro Pix da vida do cliente (sem histórico nenhum)",
      {"amount": 500}, {"approved_history_count": 0, "device_used_in_approved": False}, APPROVED, {},
      "Sem histórico não há dispositivo 'de sempre': PRF_02 não se aplica."),
    S("BASE-03", "Base", "Exemplo do PDF: R$ 1.500 às 22h15, PF",
      {"amount": 1500, "hour": 22, "minute": 15, "geo": (-23.56, -46.65)}, {}, TWO_FA, {"LIM_02": 40}),

    # ─── INT_01 ──────────────────────────────────────────────────────
    S("INT-01", "INT_01 — Mesma conta", "Origem e destino: mesmo titular, mesma agência e conta",
      {"same_account": True}, {}, REJECTED, {"INT_01": HARD}),
    S("INT-02", "INT_01 — Mesma conta", "Mesmo titular, outra conta (transferência entre contas próprias)",
      {"same_owner": True}, {}, APPROVED, {}),
    S("INT-03", "INT_01 — Mesma conta", "Contas próprias, R$ 8.000 (só o limite pesa)",
      {"same_owner": True, "amount": 8000}, {}, TWO_FA, {"LIM_01": 45}),

    # ─── LIM_01 ──────────────────────────────────────────────────────
    S("LIM1-01", "LIM_01 — Limite por transação", "PF, R$ 5.000,00 (exatamente no limite de atenção)",
      {"amount": 5000}, {}, APPROVED, {}),
    S("LIM1-02", "LIM_01 — Limite por transação", "PF, R$ 5.000,01", {"amount": 5000.01}, {}, TWO_FA, {"LIM_01": 45}),
    S("LIM1-03", "LIM_01 — Limite por transação", "PF, R$ 15.000,00 (exatamente no teto)", {"amount": 15000}, {}, TWO_FA, {"LIM_01": 45}),
    S("LIM1-04", "LIM_01 — Limite por transação", "PF, R$ 15.000,01", {"amount": 15000.01}, {}, REJECTED, {"LIM_01": HARD}),
    S("LIM1-05", "LIM_01 — Limite por transação", "PJ, R$ 25.000,00", {"payer": "PJ", "amount": 25000}, {}, APPROVED, {}),
    S("LIM1-06", "LIM_01 — Limite por transação", "PJ, R$ 25.000,01", {"payer": "PJ", "amount": 25000.01}, {}, TWO_FA, {"LIM_01": 45}),
    S("LIM1-07", "LIM_01 — Limite por transação", "PJ, R$ 100.000,00", {"payer": "PJ", "amount": 100000}, {}, TWO_FA, {"LIM_01": 45}),
    S("LIM1-08", "LIM_01 — Limite por transação", "PJ, R$ 100.000,01", {"payer": "PJ", "amount": 100000.01}, {}, REJECTED, {"LIM_01": HARD}),
    S("LIM1-09", "LIM_01 — Limite por transação", "PF, R$ 5.000,01 para destinatário conhecido",
      {"amount": 5000.01}, {"known_counterparty_count": 3}, APPROVED, {"LIM_01": 45, "CTP_03": -25},
      "45 − 25 = 20: aluguel alto para o mesmo locador passa sem fricção."),
    S("LIM1-10", "LIM_01 — Limite por transação", "PF, R$ 20.000 para destinatário conhecido",
      {"amount": 20000}, {"known_counterparty_count": 3}, REJECTED, {"LIM_01": HARD, "CTP_03": -25},
      "Redutor não salva eliminatória."),

    # ─── LIM_02 ──────────────────────────────────────────────────────
    S("LIM2-01", "LIM_02 — Valor noturno", "PF, 22h, R$ 1.000,00 (limite noturno do BC)", {"amount": 1000, "hour": 22}, {}, APPROVED, {}),
    S("LIM2-02", "LIM_02 — Valor noturno", "PF, 22h, R$ 1.000,01", {"amount": 1000.01, "hour": 22}, {}, TWO_FA, {"LIM_02": 40}),
    S("LIM2-03", "LIM_02 — Valor noturno", "PF, 22h, R$ 3.000,00", {"amount": 3000, "hour": 22}, {}, TWO_FA, {"LIM_02": 40}),
    S("LIM2-04", "LIM_02 — Valor noturno", "PF, 22h, R$ 3.000,01", {"amount": 3000.01, "hour": 22}, {}, REJECTED, {"LIM_02": HARD}),
    S("LIM2-05", "LIM_02 — Valor noturno", "PF, 19h59, R$ 2.000 (ainda é dia)", {"amount": 2000, "hour": 19, "minute": 59}, {}, APPROVED, {}),
    S("LIM2-06", "LIM_02 — Valor noturno", "PF, 20h00, R$ 2.000 (começo da noite, inclusive)", {"amount": 2000, "hour": 20}, {}, TWO_FA, {"LIM_02": 40}),
    S("LIM2-07", "LIM_02 — Valor noturno", "PF, 05h59, R$ 2.000", {"amount": 2000, "hour": 5, "minute": 59}, {}, TWO_FA, {"LIM_02": 40}),
    S("LIM2-08", "LIM_02 — Valor noturno", "PF, 06h00, R$ 2.000 (fim da noite)", {"amount": 2000, "hour": 6}, {}, APPROVED, {}),
    S("LIM2-09", "LIM_02 — Valor noturno", "PF no Acre, 19h -05:00 (00h em UTC), R$ 2.000",
      {"amount": 2000, "hour": 19, "tz": timezone(timedelta(hours=-5)), "geo": None}, {}, APPROVED, {},
      "A hora vem do fuso do payload, não do servidor. geo=None evita o disparo da regra de spoofing."),
    S("LIM2-10", "LIM_02 — Valor noturno", "PJ, 22h, R$ 5.000,00", {"payer": "PJ", "amount": 5000, "hour": 22}, {}, APPROVED, {}),
    S("LIM2-11", "LIM_02 — Valor noturno", "PJ, 22h, R$ 5.000,01 (sinal sozinho não chega a 2FA)",
      {"payer": "PJ", "amount": 5000.01, "hour": 22}, {}, APPROVED, {"LIM_02": 35}),
    S("LIM2-12", "LIM_02 — Valor noturno", "PJ, 22h, R$ 15.000,01", {"payer": "PJ", "amount": 15000.01, "hour": 22}, {}, REJECTED, {"LIM_02": HARD}),
    S("LIM2-13", "LIM_02 — Valor noturno", "PF, 22h, R$ 5.000,01 (limite e noite juntos)",
      {"amount": 5000.01, "hour": 22}, {}, REJECTED, {"LIM_01": 45, "LIM_02": HARD}),

    # ─── VEL_01 ──────────────────────────────────────────────────────
    S("VEL1-01", "VEL_01 — Rajada", "2º Pix do pagador em 2 min", {}, {"payer_attempts_2m": 1, "payer_attempts_5m": 1}, APPROVED, {}),
    S("VEL1-02", "VEL_01 — Rajada", "3º Pix do pagador em 2 min", {}, {"payer_attempts_2m": 2, "payer_attempts_5m": 2}, TWO_FA, {"VEL_01": 45}),
    S("VEL1-03", "VEL_01 — Rajada", "4º Pix em 5 min, mas só 2 nos últimos 2 min",
      {}, {"payer_attempts_2m": 1, "payer_attempts_5m": 3}, APPROVED, {}),
    S("VEL1-04", "VEL_01 — Rajada", "5º Pix em 5 min", {}, {"payer_attempts_2m": 2, "payer_attempts_5m": 4}, REJECTED, {"VEL_01": HARD}),
    S("VEL1-05", "VEL_01 — Rajada", "PJ: 14º Pix em 2 min (limite PJ é 15)", {"payer": "PJ"}, {"payer_attempts_2m": 13, "payer_attempts_5m": 13}, APPROVED, {}),
    S("VEL1-06", "VEL_01 — Rajada", "PJ: 15º Pix em 2 min", {"payer": "PJ"}, {"payer_attempts_2m": 14, "payer_attempts_5m": 14}, TWO_FA, {"VEL_01": 45}),
    S("VEL1-07", "VEL_01 — Rajada", "PJ: 25º Pix em 5 min", {"payer": "PJ"}, {"payer_attempts_2m": 14, "payer_attempts_5m": 24}, REJECTED, {"VEL_01": HARD}),

    # ─── VEL_02 ──────────────────────────────────────────────────────
    S("VEL2-01", "VEL_02 — Repetição", "Mesmo destino e valor repetido em 60 s",
      {}, {"payer_attempts_2m": 1, "payer_attempts_5m": 1, "identical_attempts_120s": 1, "identical_attempts_10m": 1}, REJECTED, {"VEL_02": HARD}),
    S("VEL2-02", "VEL_02 — Repetição", "Mesmo destino e valor repetido depois de 5 min",
      {}, {"identical_attempts_10m": 1}, APPROVED, {}),
    S("VEL2-03", "VEL_02 — Repetição", "3ª tentativa idêntica em 10 min",
      {}, {"payer_attempts_5m": 2, "identical_attempts_10m": 2}, REJECTED, {"VEL_02": HARD}),
    S("VEL2-04", "VEL_02 — Repetição", "Mesmo destino, valor diferente, em 60 s",
      {}, {"payer_attempts_2m": 1, "payer_attempts_5m": 1}, APPROVED, {},
      "Repetição exige mesmo valor; reenvio técnico (mesmo id) é idempotência, não conta aqui."),

    # ─── VEL_03 ──────────────────────────────────────────────────────
    S("VEL3-01", "VEL_03 — Muitos destinos", "2 destinatários distintos em 10 min", {}, {"other_destinations_10m": 1}, APPROVED, {}),
    S("VEL3-02", "VEL_03 — Muitos destinos", "3 destinatários distintos em 10 min", {}, {"other_destinations_10m": 2}, TWO_FA, {"VEL_03": 40}),
    S("VEL3-03", "VEL_03 — Muitos destinos", "4 destinatários distintos em 10 min", {}, {"other_destinations_10m": 3}, TWO_FA, {"VEL_03": 40}),
    S("VEL3-04", "VEL_03 — Muitos destinos", "5 destinatários distintos em 10 min", {}, {"other_destinations_10m": 4}, REJECTED, {"VEL_03": HARD}),
    S("VEL3-05", "VEL_03 — Muitos destinos", "PJ: 14 destinatários em 10 min", {"payer": "PJ"}, {"other_destinations_10m": 13}, APPROVED, {}),
    S("VEL3-06", "VEL_03 — Muitos destinos", "PJ: 15 destinatários em 10 min", {"payer": "PJ"}, {"other_destinations_10m": 14}, TWO_FA, {"VEL_03": 40}),

    # ─── MON_01 ──────────────────────────────────────────────────────
    S("MON-01", "MON_01 — Montante", "1h: R$ 3.000 antes + R$ 1.000 agora = R$ 4.000,00",
      {"amount": 1000}, {"payer_moved_sum_1h": 3000, "payer_moved_count_1h": 1, "payer_moved_sum_24h": 3000, "payer_moved_count_24h": 1}, APPROVED, {}),
    S("MON-02", "MON_01 — Montante", "1h: R$ 3.000 antes + R$ 1.000,01 agora",
      {"amount": 1000.01}, {"payer_moved_sum_1h": 3000, "payer_moved_count_1h": 1, "payer_moved_sum_24h": 3000, "payer_moved_count_24h": 1}, TWO_FA, {"MON_01": 40}),
    S("MON-03", "MON_01 — Montante", "1h: um Pix sozinho de R$ 4.500 (sem acumulação)",
      {"amount": 4500}, {}, APPROVED, {}),
    S("MON-04", "MON_01 — Montante", "24h: R$ 8.000 antes + R$ 2.000 agora = R$ 10.000,00",
      {"amount": 2000}, {"payer_moved_sum_24h": 8000, "payer_moved_count_24h": 2}, APPROVED, {}),
    S("MON-05", "MON_01 — Montante", "24h: R$ 8.000 antes + R$ 2.000,01 agora",
      {"amount": 2000.01}, {"payer_moved_sum_24h": 8000, "payer_moved_count_24h": 2}, TWO_FA, {"MON_01": 45}),
    S("MON-06", "MON_01 — Montante", "24h: R$ 18.000 antes + R$ 2.000 agora = R$ 20.000,00",
      {"amount": 2000}, {"payer_moved_sum_24h": 18000, "payer_moved_count_24h": 3}, TWO_FA, {"MON_01": 45}),
    S("MON-07", "MON_01 — Montante", "24h: R$ 18.000 antes + R$ 2.000,01 agora",
      {"amount": 2000.01}, {"payer_moved_sum_24h": 18000, "payer_moved_count_24h": 3}, REJECTED, {"MON_01": HARD}),
    S("MON-08", "MON_01 — Montante", "Um único Pix de R$ 12.000, sem histórico recente",
      {"amount": 12000}, {}, TWO_FA, {"LIM_01": 45},
      "Correção: antes o MON_01 somava +45 sobre o mesmo Pix e rejeitava (90). Acumulação exige 2+ Pix."),
    S("MON-09", "MON_01 — Montante", "1h e 24h ao mesmo tempo: vale só a faixa mais severa",
      {"amount": 3000}, {"payer_moved_sum_1h": 8000, "payer_moved_count_1h": 2, "payer_moved_sum_24h": 8000, "payer_moved_count_24h": 2}, TWO_FA, {"MON_01": 45}),
    S("MON-10", "MON_01 — Montante", "PJ, 1h: R$ 18.000 antes + R$ 2.000,01 agora (limite PJ R$ 20.000)",
      {"payer": "PJ", "amount": 2000.01}, {"payer_moved_sum_1h": 18000, "payer_moved_count_1h": 1, "payer_moved_sum_24h": 18000, "payer_moved_count_24h": 1}, TWO_FA, {"MON_01": 40}),
    S("MON-11", "MON_01 — Montante", "PJ, 24h: R$ 60.000 em vários Pix (PF rejeitaria)",
      {"payer": "PJ", "amount": 10000}, {"payer_moved_sum_24h": 50000, "payer_moved_count_24h": 5}, TWO_FA, {"MON_01": 45}),

    # ─── PRF_01 ──────────────────────────────────────────────────────
    S("PRF1-01", "PRF_01 — Desvio do ticket", "Só 2 Pix no perfil (média R$ 200), Pix de R$ 5.000 agora",
      {"amount": 5000}, {"profile_count_30d": 2, "profile_sum_30d": 400}, APPROVED, {},
      "Com menos de 3 Pix não existe régua confiável."),
    S("PRF1-02", "PRF_01 — Desvio do ticket", "Média R$ 200, Pix de R$ 999,99 (abaixo do piso de R$ 1.000)",
      {"amount": 999.99}, {"profile_count_30d": 5, "profile_sum_30d": 1000}, APPROVED, {}),
    S("PRF1-03", "PRF_01 — Desvio do ticket", "Média R$ 400, Pix de R$ 1.200,00 (exatamente 3x)",
      {"amount": 1200}, {"profile_count_30d": 5, "profile_sum_30d": 2000}, APPROVED, {}),
    S("PRF1-04", "PRF_01 — Desvio do ticket", "Média R$ 400, Pix de R$ 1.200,01",
      {"amount": 1200.01}, {"profile_count_30d": 5, "profile_sum_30d": 2000}, APPROVED, {"PRF_01": 30}),
    S("PRF1-05", "PRF_01 — Desvio do ticket", "Média R$ 400, Pix de R$ 3.200,00 (exatamente 8x)",
      {"amount": 3200}, {"profile_count_30d": 5, "profile_sum_30d": 2000}, APPROVED, {"PRF_01": 30}),
    S("PRF1-06", "PRF_01 — Desvio do ticket", "Média R$ 400, Pix de R$ 3.200,01",
      {"amount": 3200.01}, {"profile_count_30d": 5, "profile_sum_30d": 2000}, TWO_FA, {"PRF_01": 50}),
    S("PRF1-07", "PRF_01 — Desvio do ticket", "Cliente de ticket alto: média R$ 3.000, Pix de R$ 4.000",
      {"amount": 4000}, {"profile_count_30d": 10, "profile_sum_30d": 30000}, APPROVED, {}),

    # ─── PRF_02 ──────────────────────────────────────────────────────
    S("PRF2-01", "PRF_02 — Dispositivo novo", "Dispositivo novo, R$ 200,00", {"amount": 200}, {"device_used_in_approved": False}, APPROVED, {}),
    S("PRF2-02", "PRF_02 — Dispositivo novo", "Dispositivo novo, R$ 200,01", {"amount": 200.01}, {"device_used_in_approved": False}, APPROVED, {"PRF_02": 30}),
    S("PRF2-03", "PRF_02 — Dispositivo novo", "Dispositivo novo: R$ 900 hoje nele + R$ 100 agora = R$ 1.000,00",
      {"amount": 100}, {"device_used_in_approved": False, "device_moved_sum_24h": 900}, APPROVED, {}),
    S("PRF2-04", "PRF_02 — Dispositivo novo", "Dispositivo novo: R$ 900 hoje nele + R$ 100,01 agora",
      {"amount": 100.01}, {"device_used_in_approved": False, "device_moved_sum_24h": 900}, TWO_FA, {"PRF_02": 45}),
    S("PRF2-05", "PRF_02 — Dispositivo novo", "Dispositivo novo, um Pix de R$ 1.500", {"amount": 1500}, {"device_used_in_approved": False}, TWO_FA, {"PRF_02": 45}),
    S("PRF2-06", "PRF_02 — Dispositivo novo", "Dispositivo conhecido, R$ 3.000", {"amount": 3000}, {}, APPROVED, {}),
    S("PRF2-07", "PRF_02 — Dispositivo novo", "Cliente sem nenhum aprovado, dispositivo 'novo', R$ 3.000",
      {"amount": 3000}, {"approved_history_count": 0, "device_used_in_approved": False}, APPROVED, {}),

    # ─── PRF_03 ──────────────────────────────────────────────────────
    S("PRF3-01", "PRF_03 — Dispositivo compartilhado", "Dispositivo usado só por este titular", {}, {"device_other_documents_7d": 0}, APPROVED, {}),
    S("PRF3-02", "PRF_03 — Dispositivo compartilhado", "2 titulares no mesmo aparelho em 7 dias (ex.: casal)",
      {}, {"device_other_documents_7d": 1}, APPROVED, {"PRF_03": 30}),
    S("PRF3-03", "PRF_03 — Dispositivo compartilhado", "3 titulares no mesmo aparelho", {}, {"device_other_documents_7d": 2}, TWO_FA, {"PRF_03": 45}),
    S("PRF3-04", "PRF_03 — Dispositivo compartilhado", "6 titulares no mesmo aparelho (não rejeita sozinho)",
      {}, {"device_other_documents_7d": 5}, REJECTED, {"PRF_03": HARD}),

    # ─── PRF_04 ──────────────────────────────────────────────────────
    S("PRF4-01", "PRF_04 — Deslocamento", "Pix sem geolocalização (campo opcional)",
      {"geo": None}, {"last_approved_geo": geo_before(RIO, 0.5)}, APPROVED, {}),
    S("PRF4-02", "PRF_04 — Deslocamento", "Sem Pix anterior com geolocalização", {}, {}, APPROVED, {}),
    S("PRF4-03", "PRF_04 — Deslocamento", "Campinas → São Paulo (~85 km) em 10 min",
      {}, {"last_approved_geo": geo_before(CAMPINAS, 1 / 6)}, APPROVED, {},
      "Abaixo de 100 km não avalia: imprecisão de GPS geraria velocidades absurdas."),
    S("PRF4-04", "PRF_04 — Deslocamento", "Rio → São Paulo (~357 km) em 6h (~60 km/h)",
      {}, {"last_approved_geo": geo_before(RIO, 6)}, APPROVED, {}),
    S("PRF4-05", "PRF_04 — Deslocamento", "Rio → São Paulo em 1h (~357 km/h)",
      {}, {"last_approved_geo": geo_before(RIO, 1)}, TWO_FA, {"PRF_04": 45}),
    S("PRF4-06", "PRF_04 — Deslocamento", "Recife → São Paulo (~2.130 km) em 2h (~1.065 km/h)",
      {}, {"last_approved_geo": geo_before(RECIFE, 2)}, REJECTED, {"PRF_04": HARD}),
    S("PRF4-07", "PRF_04 — Deslocamento", "Rio → São Paulo no mesmo instante",
      {}, {"last_approved_geo": geo_before(RIO, 0)}, REJECTED, {"PRF_04": HARD}),

    # ─── PRF_05 ──────────────────────────────────────────────────────
    S("PRF5-01", "PRF_05 — Conta de origem nova", "Conta de 2 dias, R$ 999,99", {"amount": 999.99, "source_age": 2 * D}, {}, APPROVED, {}),
    S("PRF5-02", "PRF_05 — Conta de origem nova", "Conta de 2 dias, R$ 1.000,00", {"amount": 1000, "source_age": 2 * D}, {}, APPROVED, {"PRF_05": 30}),
    S("PRF5-03", "PRF_05 — Conta de origem nova", "Conta de exatamente 3 dias, R$ 2.000", {"amount": 2000, "source_age": 3 * D}, {}, APPROVED, {}),
    S("PRF5-04", "PRF_05 — Conta de origem nova", "Conta de 12h, R$ 3.000,00", {"amount": 3000, "source_age": 12 * H}, {}, APPROVED, {"PRF_05": 30}),
    S("PRF5-05", "PRF_05 — Conta de origem nova", "Conta de 12h, R$ 3.000,01", {"amount": 3000.01, "source_age": 12 * H}, {}, TWO_FA, {"PRF_05": 50}),
    S("PRF5-06", "PRF_05 — Conta de origem nova", "Abertura com data no futuro (tratada como recém-aberta), R$ 3.500",
      {"amount": 3500, "source_age": -2 * H}, {}, TWO_FA, {"PRF_05": 50}),

    # ─── CTP_01 ──────────────────────────────────────────────────────
    S("CTP1-01", "CTP_01 — Destino recente", "Destino de 7 dias, R$ 499,99", {"amount": 499.99, "dest_age": 7 * D}, {}, APPROVED, {}),
    S("CTP1-02", "CTP_01 — Destino recente", "Destino de exatamente 7 dias, R$ 500,00", {"amount": 500, "dest_age": 7 * D}, {}, APPROVED, {"CTP_01": 25}),
    S("CTP1-03", "CTP_01 — Destino recente", "Destino de 7 dias e 1h, R$ 1.000", {"amount": 1000, "dest_age": 7 * D + H}, {}, APPROVED, {}),
    S("CTP1-04", "CTP_01 — Destino recente", "Destino de 48h, R$ 1.999,99 (cai na faixa de 7 dias)",
      {"amount": 1999.99, "dest_age": 2 * D}, {}, APPROVED, {"CTP_01": 25}),
    S("CTP1-05", "CTP_01 — Destino recente", "Destino de exatamente 48h, R$ 2.000", {"amount": 2000, "dest_age": 2 * D}, {}, TWO_FA, {"CTP_01": 45}),
    S("CTP1-06", "CTP_01 — Destino recente", "Destino de exatamente 24h, R$ 5.000 (faixa de 48h)", {"amount": 5000, "dest_age": D}, {}, TWO_FA, {"CTP_01": 45}),
    S("CTP1-07", "CTP_01 — Destino recente", "Destino de 23h, R$ 5.000", {"amount": 5000, "dest_age": 23 * H}, {}, TWO_FA, {"CTP_01": 60}),

    # ─── CTP_02 ──────────────────────────────────────────────────────
    S("CTP2-01", "CTP_02 — Concentração no destino", "Destino PF recebeu de 4 pagadores em 1h", {}, {"dest_other_payers_1h": 3}, APPROVED, {}),
    S("CTP2-02", "CTP_02 — Concentração no destino", "Destino PF recebeu de 5 pagadores em 1h", {}, {"dest_other_payers_1h": 4}, TWO_FA, {"CTP_02": 40}),
    S("CTP2-03", "CTP_02 — Concentração no destino", "Destino PF antigo recebeu de 10 pagadores em 1h", {}, {"dest_other_payers_1h": 9}, TWO_FA, {"CTP_02": 40}),
    S("CTP2-04", "CTP_02 — Concentração no destino", "Destino PF de 10 dias recebeu de 10 pagadores em 1h",
      {"dest_age": 10 * D}, {"dest_other_payers_1h": 9}, TWO_FA, {"CTP_02": 60}),
    S("CTP2-05", "CTP_02 — Concentração no destino", "Destino PJ (loja) recebeu de 50 pagadores em 1h",
      {"receiver": "PJ"}, {"dest_other_payers_1h": 49}, APPROVED, {},
      "Correção: loja recebendo de muitos clientes é o normal; a regra vale só para destino PF."),

    # ─── CTP_03 ──────────────────────────────────────────────────────
    S("CTP3-01", "CTP_03 — Destinatário conhecido", "Destinatário conhecido, sem outros sinais (score não fica negativo)",
      {}, {"known_counterparty_count": 1}, APPROVED, {"CTP_03": -25}),
    S("CTP3-02", "CTP_03 — Destinatário conhecido", "Conhecido + destino concentrando pagadores",
      {}, {"known_counterparty_count": 2, "dest_other_payers_1h": 4}, APPROVED, {"CTP_02": 40, "CTP_03": -25}),

    # ─── Faixas de decisão ───────────────────────────────────────────
    S("DEC-01", "Faixas de decisão", "Score 35 → approved (abaixo de 40)", {"payer": "PJ", "amount": 5000.01, "hour": 22}, {}, APPROVED, {"LIM_02": 35}),
    S("DEC-02", "Faixas de decisão", "Score 40 → 2FA (limite inferior)", {"amount": 1500, "hour": 22}, {}, TWO_FA, {"LIM_02": 40}),
    S("DEC-03", "Faixas de decisão", "Score 75 → 2FA", {"amount": 6000}, {"device_other_documents_7d": 1}, TWO_FA, {"LIM_01": 45, "PRF_03": 30}),
    S("DEC-04", "Faixas de decisão", "Score 80 → rejected (limite inferior)",
      {"amount": 1500, "hour": 22}, {"other_destinations_10m": 2}, REJECTED, {"LIM_02": 40, "VEL_03": 40}),

    # ─── Histórias de ponta a ponta ──────────────────────────────────
    S("HIST-01", "Histórias", "Aluguel mensal de R$ 2.500 para o mesmo locador",
      {"amount": 2500}, {"known_counterparty_count": 6, "profile_count_30d": 8, "profile_sum_30d": 6000}, APPROVED, {"PRF_01": 30, "CTP_03": -25},
      "O aluguel destoa do ticket médio (R$ 750) e soma 30, mas o destinatário conhecido tira 25: score 5."),
    S("HIST-02", "Histórias", "Celular novo, compra de R$ 150 no mercado",
      {"amount": 150}, {"device_used_in_approved": False}, APPROVED, {}),
    S("HIST-03", "Histórias", "Celular novo, primeira compra de R$ 300", {"amount": 300}, {"device_used_in_approved": False}, APPROVED, {"PRF_02": 30}),
    S("HIST-04", "Histórias", "Conta invadida: 23h, R$ 2.500, aparelho novo, destino aberto há 2 dias, cliente de ticket R$ 150",
      {"amount": 2500, "hour": 23, "dest_age": 2 * D},
      {"device_used_in_approved": False, "profile_count_30d": 5, "profile_sum_30d": 750},
      REJECTED, {"LIM_02": 40, "PRF_01": 50, "PRF_02": 45, "CTP_01": 45}),
    S("HIST-05", "Histórias", "Golpe do falso parente: vítima no próprio celular, de dia, R$ 3.000 para PF que recebeu de 6 pessoas na última hora",
      {"amount": 3000, "dest_age": 6 * D}, {"dest_other_payers_1h": 5, "profile_count_30d": 8, "profile_sum_30d": 1600},
      REJECTED, {"PRF_01": 50, "CTP_01": 25, "CTP_02": 40},
      "O 2FA não protege no golpe (é o próprio cliente confirmando): por isso contraparte e perfil somam até rejeitar."),
    S("HIST-06", "Histórias", "Golpe com cliente sem histórico recente: só a contraparte aparece",
      {"amount": 3000, "dest_age": 6 * D}, {"dest_other_payers_1h": 5}, TWO_FA, {"CTP_01": 25, "CTP_02": 40},
      "Limitação conhecida: sem régua de perfil, o golpe cai em 2FA."),
    S("HIST-07", "Histórias", "Conta laranja coletora: PF aberta há 5 dias, 11 pagadores na última hora, R$ 800",
      {"amount": 800, "dest_age": 5 * D}, {"dest_other_payers_1h": 10}, REJECTED, {"CTP_01": 25, "CTP_02": 60}),
    S("HIST-08", "Histórias", "Sequestro relâmpago: 23h, R$ 5.000, celular da própria vítima",
      {"amount": 5000, "hour": 23}, {}, REJECTED, {"LIM_02": HARD}),
    S("HIST-09", "Histórias", "Script esvaziando a conta: 5º Pix de R$ 900 em 3 min, cada um para um destino",
      {"amount": 900}, {"payer_attempts_2m": 3, "payer_attempts_5m": 4, "other_destinations_10m": 4,
                        "payer_moved_sum_1h": 1800, "payer_moved_count_1h": 2, "payer_moved_sum_24h": 1800, "payer_moved_count_24h": 2},
      REJECTED, {"VEL_01": HARD, "VEL_03": HARD}),
    S("HIST-10", "Histórias", "Fracionamento: 3º Pix de R$ 1.900 na mesma hora",
      {"amount": 1900}, {"payer_moved_sum_1h": 3800, "payer_moved_count_1h": 2, "payer_moved_sum_24h": 3800, "payer_moved_count_24h": 2},
      TWO_FA, {"MON_01": 40}),
    S("HIST-11", "Histórias", "Empresa pagando 8 fornecedores de R$ 3.000 em 10 min",
      {"payer": "PJ", "amount": 3000}, {"payer_attempts_2m": 3, "payer_attempts_5m": 5, "other_destinations_10m": 7,
                                        "payer_moved_sum_1h": 21000, "payer_moved_count_1h": 7, "payer_moved_sum_24h": 21000, "payer_moved_count_24h": 7},
      TWO_FA, {"MON_01": 40},
      "Atrito conhecido: lote grande de PJ pede uma confirmação."),
    S("HIST-12", "Histórias", "Conta recém-aberta do pagador mandando R$ 3.500 para destino aberto ontem",
      {"amount": 3500, "source_age": 10 * H, "dest_age": 30 * H}, {"approved_history_count": 0, "device_used_in_approved": False},
      REJECTED, {"PRF_05": 50, "CTP_01": 45}),
    S("HIST-13", "Histórias", "Casal dividindo o celular, Pix de R$ 80", {"amount": 80}, {"device_other_documents_7d": 1}, APPROVED, {"PRF_03": 30}),
    S("HIST-14", "Histórias", "Fazenda de contas: aparelho com 5 titulares, conta de 2 dias, R$ 1.000",
      {"amount": 1000, "source_age": 2 * D}, {"device_other_documents_7d": 4}, REJECTED, {"PRF_03": HARD, "PRF_05": 30}),
    S("HIST-15", "Histórias", "Viagem de avião: Pix no Rio 1h depois do último em São Paulo",
      {"geo": RIO}, {"last_approved_geo": geo_before(SAO_PAULO, 1)}, TWO_FA, {"PRF_04": 45},
      "Falso positivo aceito: custa uma confirmação."),
    S("HIST-16", "Histórias", "Salário: cliente transfere R$ 4.000 para a própria conta em outro banco aberta há 1 ano",
      {"amount": 4000, "same_owner": True, "dest_age": timedelta(days=365)}, {}, APPROVED, {}),
    S("HIST-17", "Histórias", "Account Takeover clássico: Device novo, conta nova recém-aberta, valor alto",
      {"amount": 10000, "source_age": 1 * H}, 
      {"device_used_in_approved": False},
      REJECTED, {"PRF_02": 45, "PRF_05": 50, "LIM_01": 45}),
    S("HIST-18", "Histórias", "Invasão: GPS aponta para SP, mas fuso horário alterado para UTC-5 para burlar regra noturna",
      {"amount": 100, "hour": 22, "tz": timezone(timedelta(hours=-5)), "geo": SAO_PAULO}, 
      {}, # O histórico vazio evita disparar regras de aparelho novo
      REJECTED, {"PRF_06": "HARD"}),
]
