"""A política antifraude: todos os parâmetros do motor, num lugar só.

Valores monetários em CENTAVOS (R$ 1.000,00 = 100_000), como o `amount`
do payload. Janelas de tempo em segundos.

Regra de leitura dos limites:
  • "acima de X"  → valor >  X
  • "a partir de" → valor >= X
Os nomes dos campos abaixo dizem qual dos dois é usado.

Mudou um número aqui? Suba o POLICY_VERSION: ele é gravado em cada
análise (risk_analysis.rules_version) e diz qual política decidiu cada Pix.
"""

ENGINE_VERSION = "1.0.0"
POLICY_VERSION = "2026-10-17.1"

# ── Faixas de decisão ────────────────────────────────────────────────
TWO_FACTOR_FROM_SCORE = 40   # score >= 40 → two_factor_required
REJECT_FROM_SCORE = 80       # score >= 80 → rejected

# ── Período noturno (hora local do payload) ──────────────────────────
NIGHT_START_HOUR = 20        # 20:00 inclusive
NIGHT_END_HOUR = 6           # até 05:59

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

# ── LIMITE ───────────────────────────────────────────────────────────
LIM_01 = {
    "PF": {"attention_above": 500_000, "points": 45, "reject_above": 1_500_000},
    "PJ": {"attention_above": 2_500_000, "points": 45, "reject_above": 10_000_000},
}

LIM_02 = {
    # PF: R$ 1.000 é o limite noturno padrão do Banco Central para pessoa
    # física. Acima dele, o cliente precisa ter pedido aumento: pedimos
    # confirmação (40 = 2FA sozinho). Acima de R$ 3.000 rejeita: no
    # sequestro relâmpago a vítima confirma o 2FA sob coação.
    "PF": {"attention_above": 100_000, "points": 40, "reject_above": 300_000},
    "PJ": {"attention_above": 500_000, "points": 35, "reject_above": 1_500_000},
}

# ── VELOCITY ─────────────────────────────────────────────────────────
# Contagens INCLUEM o Pix atual. Para PJ as contagens são multiplicadas
# (pagamento a fornecedores / folha em lote é comportamento normal).
PJ_COUNT_MULTIPLIER = 5

VEL_01 = {
    "attention_window": 2 * MINUTE, "attention_count": 3, "points": 45,
    "reject_window": 5 * MINUTE, "reject_count": 5,
}

VEL_02 = {
    "attention_window": 120, 
    "attention_count": 2, 
    "points": 45,
    "reject_window": 10 * MINUTE, 
    "reject_count": 3,
    "fatal_on_duplicate": True,
}

VEL_03 = {
    "window": 10 * MINUTE, "attention_count": 3, "points": 40, "reject_count": 5,
}

# ── MONTANTE ─────────────────────────────────────────────────────────
# Soma = Pix aprovados + Pix em 2FA na janela + o Pix atual. Rejeitados
# não somam (o dinheiro não saiu). Todas as faixas exigem pelo menos 2
# Pix na janela: um Pix sozinho, por maior que seja, é assunto do LIM_01.
PJ_AMOUNT_MULTIPLIER = 5

MON_01 = {
    "min_count": 2,
    "hour_window": HOUR, "hour_above": 400_000, "hour_points": 40,
    "day_window": DAY, "day_above": 1_000_000, "day_points": 45,
    "day_reject_above": 2_000_000,
}

# ── PERFIL ───────────────────────────────────────────────────────────
PROFILE_WINDOW = 30 * DAY    # janela do perfil do cliente (só aprovados)

PRF_01 = {
    "min_history": 3, "min_amount": 100_000,
    "attention_multiplier": 3, "attention_points": 30,
    "high_multiplier": 8, "high_points": 50,
}

PRF_02 = {
    # Alinhado ao Banco Central para dispositivo não cadastrado:
    # R$ 200 por transação e R$ 1.000 por dia.
    "amount_above": 20_000, "points": 30,
    "day_window": DAY, "day_amount_above": 100_000, "day_points": 45,
}

PRF_03 = {
    "window": 7 * DAY, "attention_documents": 2, "attention_points": 30,
    "high_documents": 3, "high_points": 45,
}

PRF_04 = {
    "min_distance_km": 100,
    "attention_speed_kmh": 300, "attention_points": 45,
    "high_speed_kmh": 800, "high_points": 60,
}

PRF_05 = {
    "recent_age": 3 * DAY, "recent_min_amount": 100_000, "recent_points": 30,
    "brand_new_age": DAY, "brand_new_amount_above": 300_000, "brand_new_points": 50,
}

PRF_06 = {
    # Tolerância de 1 hora devido a fronteiras ou horários de verão antigos. 
    # Diferença >= 2 horas entre o GPS e o relógio do telemóvel = Fraude.
    "max_tz_divergence_hours": 2, 
}

# ── CONTRAPARTE ──────────────────────────────────────────────────────
CTP_01 = [
    # da faixa mais severa para a mais branda; a primeira que casar vale
    {"max_age": DAY, "inclusive": False, "min_amount": 500_000, "points": 60},
    {"max_age": 2 * DAY, "inclusive": True, "min_amount": 200_000, "points": 45},
    {"max_age": 7 * DAY, "inclusive": True, "min_amount": 50_000, "points": 25},
]

CTP_02 = {
    # Só destino PF: loja (PJ) recebendo de muitos clientes é o normal.
    "window": HOUR,
    "attention_payers": 5, "attention_points": 40,
    "high_payers": 10, "high_max_dest_age": 30 * DAY, "high_points": 60,
}

CTP_03 = {
    "min_relationship_age": DAY, "min_approved": 1, "points": -25,
}
