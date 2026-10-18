"""Gera docs/cenarios.md a partir do catálogo de testes.

    python scripts/gerar_cenarios.py

O documento é o resultado de RODAR o motor em cada cenário de
tests/unit/scenario_catalog.py — não é escrito à mão. Se a política mudar,
rode de novo; se o resultado divergir do esperado no catálogo, o
test_scenarios.py fica vermelho antes.
"""

import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "unit"))

from engine import policy  # noqa: E402
from engine.decision import evaluate  # noqa: E402
from scenario_catalog import CATALOG  # noqa: E402

STATUS_LABEL = {
    "approved": "✅ approved",
    "two_factor_required": "🔐 2FA",
    "rejected": "⛔ rejected",
}


def describe_hits(decision) -> str:
    if not decision.hits:
        return "—"
    parts = []
    for hit in decision.hits:
        parts.append(f"{hit.rule_code} (eliminatória)" if hit.hard_reject else f"{hit.rule_code} ({hit.points:+d})")
    return ", ".join(parts)


def main() -> None:
    groups = OrderedDict()
    for scenario in CATALOG:
        groups.setdefault(scenario.group, []).append(scenario)

    totals = {"approved": 0, "two_factor_required": 0, "rejected": 0}
    lines = [
        "# Cenários do motor antifraude",
        "",
        f"Gerado por `scripts/gerar_cenarios.py` a partir de `tests/unit/scenario_catalog.py` "
        f"(política `{policy.POLICY_VERSION}`). Cada linha é um teste automatizado.",
        "",
        "**Pix base de todos os cenários:** PF → PF, quinta-feira 15/10/2026 às 14h (-03:00), R$ 100,00, "
        "contas abertas há anos, celular que o cliente já usa, cliente com 10 Pix aprovados antigos e nada recente. "
        "Cada cenário muda só o que está escrito nele. \"Antes\" = histórico que já existia quando o Pix chegou.",
        "",
        "Faixas: score < 40 → approved · 40 a 79 → two_factor_required · ≥ 80 → rejected. "
        "Regra eliminatória rejeita sozinha, e redutor não a desfaz.",
        "",
    ]

    for group, scenarios in groups.items():
        lines += [f"## {group}", "", "| ID | Cenário | Regras disparadas | Score | Decisão |", "|---|---|---|---|---|"]
        notes = []
        for scenario in scenarios:
            pix, history = scenario.build()
            decision = evaluate(pix, history)
            totals[decision.status] += 1
            lines.append(
                f"| {scenario.id} | {scenario.title} | {describe_hits(decision)} | {decision.score} | {STATUS_LABEL[decision.status]} |"
            )
            if scenario.note:
                notes.append(f"- **{scenario.id}:** {scenario.note}")
        lines.append("")
        if notes:
            lines += notes + [""]

    lines += [
        "## Resumo",
        "",
        f"{len(CATALOG)} cenários: {totals['approved']} approved, "
        f"{totals['two_factor_required']} two_factor_required, {totals['rejected']} rejected.",
        "",
    ]

    output = ROOT / "docs" / "cenarios.md"
    output.parent.mkdir(exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"{output.relative_to(ROOT)}: {len(CATALOG)} cenários")


if __name__ == "__main__":
    main()
