import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional
import lightgbm as lgb
import numpy as np
import pandas as pd
from utils.logger import get_logger
from utils.ml_features import compute_features_online, row_from_pix

logger = get_logger(__name__)
ARTIFACTS_DIR = Path(__file__).resolve().parent / "ml_artifacts"


def _brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _n(v) -> int:
    return int(round(v))


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {(singular if n == 1 else plural)}"


def _age(v, what: str) -> str:
    return f"{what} aberta hoje" if _n(v) == 0 else f"{what} aberta há {_plural(_n(v), 'dia', 'dias')}"


REASON_TEXT = {
    "amount_brl": lambda v: f"valor de {_brl(v)}",
    "is_night": lambda v: "Pix de madrugada",
    "source_account_age_days": lambda v: _age(v, "conta de origem"),
    "dest_account_age_days": lambda v: _age(v, "conta destino"),
    "payer_tx_count_1h": lambda v: f"{_n(v)} Pix do pagador na última hora",
    "payer_tx_count_24h": lambda v: f"{_n(v)} Pix do pagador nas últimas 24h",
    "payer_amount_sum_24h": lambda v: f"{_brl(v)} enviados pelo pagador nas últimas 24h",
    "payer_tx_count_90d": lambda v: (
        f"histórico curto: {_n(v)} Pix nos últimos 90 dias" if v else "pagador sem histórico nos últimos 90 dias"
    ),
    "ratio_to_median": lambda v: f"valor {v:.1f}x o valor típico do pagador",
    "is_new_dest_for_payer": lambda v: "primeiro Pix para este destinatário",
    "dest_distinct_payers_24h": lambda v: f"destino recebeu de {_plural(_n(v), 'pagador', 'pagadores diferentes')} em 24h",
    "dest_distinct_payers_7d": lambda v: f"destino recebeu de {_plural(_n(v), 'pagador', 'pagadores diferentes')} em 7 dias",
    "is_new_device_for_payer": lambda v: "aparelho nunca usado por esta conta",
    "device_distinct_accounts_7d": lambda v: f"aparelho usado por {_plural(_n(v), 'outra conta', 'outras contas')} em 7 dias",
    "ip_distinct_accounts_24h": lambda v: f"IP usado por {_plural(_n(v), 'outra conta', 'outras contas')} em 24h",
    "km_from_usual_location": lambda v: f"{_n(v)} km da localização habitual",
    "geo_missing": lambda v: "Pix enviado sem geolocalização",
}
RISKY = {
    "amount_brl": lambda v: v >= 1000,
    "is_night": lambda v: v == 1,
    "source_account_age_days": lambda v: v < 90,
    "dest_account_age_days": lambda v: v < 90,
    "payer_tx_count_1h": lambda v: v >= 2,
    "payer_tx_count_24h": lambda v: v >= 4,
    "payer_amount_sum_24h": lambda v: v >= 2000,
    "payer_tx_count_90d": lambda v: v < 3,
    "ratio_to_median": lambda v: v >= 3,
    "is_new_dest_for_payer": lambda v: v == 1,
    "dest_distinct_payers_24h": lambda v: v >= 3,
    "dest_distinct_payers_7d": lambda v: v >= 5,
    "is_new_device_for_payer": lambda v: v == 1,
    "device_distinct_accounts_7d": lambda v: v >= 1,
    "ip_distinct_accounts_24h": lambda v: v >= 2,
    "km_from_usual_location": lambda v: v >= 100,
    "geo_missing": lambda v: v == 1,
}
SAME_SIGNAL = {
    "dest_distinct_payers_7d": "dest_distinct_payers",
    "dest_distinct_payers_24h": "dest_distinct_payers",
    "payer_tx_count_1h": "payer_velocity",
    "payer_tx_count_24h": "payer_velocity",
    "payer_amount_sum_24h": "payer_velocity",
    "local_hour": "night",
    "is_night": "night",
}


class FraudModel:

    def __init__(self, artifacts_dir: Path = ARTIFACTS_DIR) -> None:
        with open(artifacts_dir / "preprocess.json", encoding="utf-8") as f:
            self.spec = json.load(f)
        self.booster = lgb.Booster(model_file=str(artifacts_dir / "model.txt"))
        self.version = self.spec["model_version"]
        self.thresholds = self.spec["thresholds"]
        self.columns = self.spec["output_columns"]

    def transform(self, features: pd.DataFrame) -> pd.DataFrame:
        spec, out = (self.spec, {})
        for f in spec["num_features"]:
            out[f] = pd.to_numeric(features[f], errors="coerce").astype(float).fillna(spec["num_medians"][f])
        for f in spec["missing_indicator_features"]:
            out["missingindicator_" + f] = features[f].isna().astype(float)
        for f in spec["cat_features"]:
            values = features[f].astype(object).where(features[f].notna(), "unknown").astype(str)
            for c in spec["cat_categories"][f]:
                out[f"{f}_{c}"] = (values == c).astype(float)
        return pd.DataFrame(out)[self.columns]

    def predict(self, features: pd.DataFrame) -> dict:
        X = self.transform(features).to_numpy()
        score = float(self.booster.predict(X)[0])
        contribs = self.booster.predict(X, pred_contrib=True)[0][:-1]
        return {"score": score, "factors": self._top_factors(features.iloc[0], contribs)}

    def _top_factors(self, raw: pd.Series, contribs: np.ndarray, top: int = 3, min_contrib: float = 0.15) -> list:
        totals = {}
        for name, value in zip(self.columns, contribs):
            base = name[len("missingindicator_") :] if name.startswith("missingindicator_") else name
            base = "channel" if base.startswith("channel_") else base
            totals[base] = totals.get(base, 0.0) + float(value)
        factors, used = ([], set())
        for feat, value in sorted(totals.items(), key=lambda kv: -kv[1]):
            if value < min_contrib or len(factors) >= top:
                break
            group = SAME_SIGNAL.get(feat, feat)
            if group in used or feat not in RISKY:
                continue
            raw_value = raw[feat]
            if isinstance(raw_value, float) and math.isnan(raw_value):
                continue
            if not RISKY[feat](raw_value):
                continue
            factors.append(
                {
                    "feature": feat,
                    "value": _json_safe(raw_value),
                    "contribution": round(value, 3),
                    "text": REASON_TEXT[feat](raw_value),
                }
            )
            used.add(group)
        return factors


def _json_safe(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return round(float(v), 4)
    return v


@lru_cache(maxsize=1)
def load_model() -> FraudModel:
    return FraudModel()


def score_pix(pix, history: pd.DataFrame) -> Optional[dict]:
    try:
        features = compute_features_online(row_from_pix(pix), history)
        model = load_model()
        result = model.predict(features)
    except Exception:
        logger.exception("Falha ao calcular o score do modelo comportamental")
        return None
    current = features.iloc[0]
    return {
        "score": round(result["score"], 4),
        "factors": result["factors"],
        "thresholds": model.thresholds,
        "model_version": model.version,
        "payer_history_count": int(current["payer_tx_count_90d"]),
        "source_account_age_days": int(current["source_account_age_days"]),
    }
