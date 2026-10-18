"""Como as regras viram decisão.

1. Roda todas as regras (cada uma devolve no máximo um RuleHit).
2. Se alguma for eliminatória → rejected, decidido por 'hard_rule'.
   Redutores (CTP_03) não salvam uma eliminatória.
3. Senão: score = max(0, soma dos pontos) e aplica as faixas
   (< 40 approved · 40–79 two_factor_required · >= 80 rejected).

O score é calculado também quando há eliminatória, para ficar registrado
quanto os outros sinais somavam.
"""

from typing import List

from engine import policy
from engine.rules import RULES
from engine.types import Decision, HistorySnapshot, PixData, RuleHit, build_rule_context

APPROVED = "approved"
TWO_FACTOR = "two_factor_required"
REJECTED = "rejected"


def decide(hits: List[RuleHit]) -> Decision:
    score = max(0, sum(hit.points for hit in hits))

    if any(hit.hard_reject for hit in hits):
        return Decision(status=REJECTED, score=score, decided_by="hard_rule", hits=hits)

    if score >= policy.REJECT_FROM_SCORE:
        status = REJECTED
    elif score >= policy.TWO_FACTOR_FROM_SCORE:
        status = TWO_FACTOR
    else:
        status = APPROVED

    return Decision(status=status, score=score, decided_by="score", hits=hits)


def evaluate(pix: PixData, history: HistorySnapshot) -> Decision:
    context = build_rule_context(pix, history)

    hits = []
    for rule in RULES:
        hit = rule(pix, context)
        if hit is not None:
            hits.append(hit)

    return decide(hits)


def build_metadata(decision: Decision) -> dict:
    """O `metadata` da resposta — e exatamente o que fica gravado."""
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
