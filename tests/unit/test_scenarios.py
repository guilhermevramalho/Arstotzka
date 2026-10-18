"""Roda cada cenário do catálogo e confere decisão + regras disparadas.

Se este teste falha, ou a regra mudou ou o catálogo (e portanto o
docs/cenarios.md) está desatualizado. Os dois precisam andar juntos.
"""

import pytest

from engine.decision import evaluate
from scenario_catalog import CATALOG, HARD


def triggered(decision) -> dict:
    return {hit.rule_code: (HARD if hit.hard_reject else hit.points) for hit in decision.hits}


def test_catalog_ids_are_unique():
    ids = [scenario.id for scenario in CATALOG]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("scenario", CATALOG, ids=[scenario.id for scenario in CATALOG])
def test_scenario(scenario):
    pix, history = scenario.build()

    decision = evaluate(pix, history)

    assert triggered(decision) == scenario.expected, scenario.title
    assert decision.status == scenario.expected_status, scenario.title
