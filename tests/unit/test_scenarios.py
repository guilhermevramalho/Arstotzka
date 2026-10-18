import pytest
from controllers.pix_transaction_controller import PixTransactionController
from scenario_catalog import CATALOG, HARD

controller = PixTransactionController.__new__(PixTransactionController)


def triggered(decision) -> dict:
    return {hit.rule_code: HARD if hit.hard_reject else hit.points for hit in decision.hits}


def test_catalog_ids_are_unique():
    ids = [scenario.id for scenario in CATALOG]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("scenario", CATALOG, ids=[scenario.id for scenario in CATALOG])
def test_scenario(scenario):
    pix, history = scenario.build()
    decision = controller.evaluate(pix, history)
    assert triggered(decision) == scenario.expected, scenario.title
    assert decision.status == scenario.expected_status, scenario.title
