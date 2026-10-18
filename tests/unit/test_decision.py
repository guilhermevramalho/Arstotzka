from utils import policy
from utils.types import RuleHit
from controllers.pix_transaction_controller import PixTransactionController

controller = PixTransactionController.__new__(PixTransactionController)


def hit(code: str, points: int, hard: bool = False) -> RuleHit:
    return RuleHit(code, "LIMITE", 0 if hard else points, "motivo", hard_reject=hard)


def test_no_hits_is_approved_with_zero_score():
    decision = controller._decide([])
    assert (decision.status, decision.score, decision.decided_by) == ("approved", 0, "score")


def test_score_bands_edges():
    assert controller._decide([hit("LIM_01", policy.TWO_FACTOR_FROM_SCORE - 1)]).status == "approved"
    assert controller._decide([hit("LIM_01", policy.TWO_FACTOR_FROM_SCORE)]).status == "two_factor_required"
    assert controller._decide([hit("LIM_01", policy.REJECT_FROM_SCORE - 1)]).status == "two_factor_required"
    assert controller._decide([hit("LIM_01", policy.REJECT_FROM_SCORE)]).status == "rejected"


def test_score_never_negative():
    decision = controller._decide([hit("CTP_03", -25)])
    assert decision.score == 0
    assert decision.status == "approved"


def test_attenuator_reduces_score_across_band():
    decision = controller._decide([hit("LIM_01", 45), hit("CTP_03", -25)])
    assert (decision.score, decision.status) == (20, "approved")


def test_hard_reject_wins_over_attenuator_and_low_score():
    decision = controller._decide([hit("LIM_01", 0, hard=True), hit("CTP_03", -25)])
    assert decision.status == "rejected"
    assert decision.decided_by == "hard_rule"
    assert decision.hard_reject is True
    assert decision.score == 0


def test_score_is_still_recorded_when_hard_reject():
    decision = controller._decide([hit("LIM_02", 0, hard=True), hit("PRF_02", 45)])
    assert decision.score == 45
    assert decision.decided_by == "hard_rule"


def test_metadata_shape():
    decision = controller._decide([hit("LIM_02", 40)])
    metadata = controller.build_metadata(decision)
    assert metadata["engine_version"] == policy.ENGINE_VERSION
    assert metadata["policy_version"] == policy.POLICY_VERSION
    assert metadata["score"] == 40
    assert metadata["decision"] == "two_factor_required"
    assert metadata["hard_reject"] is False
    assert metadata["triggered_rules"] == [
        {
            "rule_id": "LIM_02",
            "family": "LIMITE",
            "points": 40,
            "hard_reject": False,
            "reason": "motivo",
            "evidence": {},
        }
    ]
