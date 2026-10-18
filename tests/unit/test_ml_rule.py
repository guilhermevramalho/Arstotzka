from datetime import datetime, timedelta, timezone
import pandas as pd
from controllers.pix_transaction_controller import PixTransactionController
from utils import policy
from utils.ml_model import load_model, score_pix
from utils.types import HistorySnapshot, PixData, build_rule_context

controller = PixTransactionController.__new__(PixTransactionController)
TZ = timezone(timedelta(hours=-3))
NOW = datetime(2026, 10, 18, 14, 30, tzinfo=TZ)
HABITUAL_DEST = ("60701190", "0001", "123456", "98765432100")


def make_pix(**overrides) -> PixData:
    values = {
        "pix_id": "pix-ml-001",
        "amount": 15000,
        "transaction_date": NOW,
        "local_hour": NOW.hour,
        "source_branch": "0001",
        "source_account_number": "88213",
        "source_document": "12345678909",
        "source_opening_date": NOW - timedelta(days=900),
        "dest_participant": HABITUAL_DEST[0],
        "dest_branch": HABITUAL_DEST[1],
        "dest_account_number": HABITUAL_DEST[2],
        "dest_document": HABITUAL_DEST[3],
        "dest_opening_date": NOW - timedelta(days=2000),
        "device_id": "dvc-habitual",
        "channel": "app",
        "ip": "177.10.20.30",
        "latitude": -23.55,
        "longitude": -46.63,
    }
    values.update(overrides)
    return PixData(**values)


def habitual_history(count: int = 12) -> pd.DataFrame:
    rows = []
    for day in range(2, 2 + count * 5, 5):
        moment = NOW - timedelta(days=day)
        rows.append(
            {
                "pix_id": f"pix-hist-{day}",
                "amount": 15000,
                "transaction_date": moment,
                "local_hour": moment.hour,
                "source_branch": "0001",
                "source_account_number": "88213",
                "source_document": "12345678909",
                "source_opening_date": NOW - timedelta(days=900),
                "dest_participant": HABITUAL_DEST[0],
                "dest_branch": HABITUAL_DEST[1],
                "dest_account_number": HABITUAL_DEST[2],
                "dest_document": HABITUAL_DEST[3],
                "dest_opening_date": NOW - timedelta(days=2000),
                "device_id": "dvc-habitual",
                "channel": "app",
                "ip": "177.10.20.30",
                "latitude": -23.55,
                "longitude": -46.63,
            }
        )
    return pd.DataFrame(rows)


def account_takeover_pix() -> PixData:
    return make_pix(
        amount=480000,
        local_hour=3,
        transaction_date=NOW.replace(hour=3),
        dest_participant="18236120",
        dest_branch="0042",
        dest_account_number="777001",
        dest_document="11122233344",
        dest_opening_date=NOW - timedelta(days=1),
        device_id="dvc-desconhecido",
        ip="45.12.13.14",
        latitude=-3.73,
        longitude=-38.52,
    )


def prf_07(pix: PixData, ml_history):
    context = build_rule_context(pix, HistorySnapshot(ml_history=ml_history))
    return controller._prf_07_behavioral_score(pix, context)


def test_model_loads_with_thresholds():
    model = load_model()
    assert 0 < model.thresholds["two_factor"] <= model.thresholds["reject"] < 1


def test_habitual_pix_does_not_fire():
    assert prf_07(make_pix(), habitual_history()) is None


def test_account_takeover_fires_high_risk_with_reasons():
    hit = prf_07(account_takeover_pix(), habitual_history())
    assert hit is not None
    assert hit.rule_code == "PRF_07"
    assert hit.family == "PERFIL"
    assert hit.points == policy.PRF_07["high_points"]
    assert not hit.hard_reject
    assert hit.evidence["score"] >= hit.evidence["threshold"]
    assert hit.evidence["factors"]
    assert "Modelo comportamental indica risco alto" in hit.reason


def test_behavioral_signal_alone_never_rejects():
    hit = prf_07(account_takeover_pix(), habitual_history())
    decision = controller._decide([hit])
    assert decision.status == "two_factor_required"


def test_cold_start_old_account_without_history_is_skipped():
    assert prf_07(account_takeover_pix(), habitual_history(count=0)) is None


def test_new_source_account_without_history_is_scored():
    pix = make_pix(
        amount=250000,
        source_opening_date=NOW - timedelta(hours=6),
        dest_participant="18236120",
        dest_branch="0042",
        dest_account_number="777001",
        dest_document="11122233344",
        dest_opening_date=NOW - timedelta(days=2),
        device_id="dvc-fazenda",
    )
    result = score_pix(pix, habitual_history(count=0))
    assert result is not None
    assert result["payer_history_count"] == 0
    assert prf_07(pix, habitual_history(count=0)) is not None


def test_rule_is_skipped_without_history_data():
    assert prf_07(account_takeover_pix(), None) is None


def test_model_failure_never_becomes_fraud():
    broken_history = pd.DataFrame([{"transaction_date": "data inválida"}])
    assert prf_07(account_takeover_pix(), broken_history) is None


def test_only_previous_pix_are_used():
    pix = account_takeover_pix()
    future = habitual_history()
    future["transaction_date"] = future["transaction_date"] + timedelta(days=200)
    assert score_pix(pix, future)["payer_history_count"] == 0
