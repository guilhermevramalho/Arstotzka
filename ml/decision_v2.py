import json
import math
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from features_v2 import CAT_FEATURES, FEATURE_COLS

COLD_START_MIN_AGE_DAYS = 30
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _n(v):
    return int(round(v))


def _plural(n, singular, plural):
    return f"{n} {(singular if n == 1 else plural)}"


REASON_TEXT = {
    "amount_brl": lambda v: f"valor de {brl(v)}",
    "local_hour": lambda v: f"Pix às {_n(v)}h",
    "day_of_week": lambda v: f"Pix numa {DIAS[_n(v)]}",
    "is_night": lambda v: "Pix de madrugada" if v else "Pix em horário comercial",
    "source_is_pj": lambda v: "pagador é empresa" if v else "pagador é pessoa física",
    "dest_is_pj": lambda v: "recebedor é empresa" if v else "recebedor é pessoa física",
    "source_account_age_days": lambda v: (
        "conta de origem aberta hoje" if _n(v) == 0 else f"conta de origem aberta há {_plural(_n(v), 'dia', 'dias')}"
    ),
    "dest_account_age_days": lambda v: (
        "conta destino aberta hoje" if _n(v) == 0 else f"conta destino aberta há {_plural(_n(v), 'dia', 'dias')}"
    ),
    "payer_tx_count_1h": lambda v: f"{_n(v)} Pix do pagador na última hora",
    "payer_tx_count_24h": lambda v: f"{_n(v)} Pix do pagador nas últimas 24h",
    "payer_amount_sum_24h": lambda v: f"{brl(v)} enviados pelo pagador nas últimas 24h",
    "payer_tx_count_90d": lambda v: (
        f"histórico curto: {_n(v)} Pix nos últimos 90 dias" if v else "pagador sem histórico nos últimos 90 dias"
    ),
    "payer_median_amount_90d": lambda v: f"valor típico do pagador é {brl(v)}",
    "ratio_to_median": lambda v: f"valor {v:.1f}x o valor típico do pagador",
    "is_new_dest_for_payer": lambda v: "primeiro Pix para este destinatário" if v else "destinatário já conhecido",
    "dest_distinct_payers_24h": lambda v: f"destino recebeu de {_plural(_n(v), 'pagador', 'pagadores diferentes')} em 24h",
    "dest_distinct_payers_7d": lambda v: f"destino recebeu de {_plural(_n(v), 'pagador', 'pagadores diferentes')} em 7 dias",
    "is_new_device_for_payer": lambda v: "aparelho nunca usado por esta conta" if v else "aparelho habitual da conta",
    "device_distinct_accounts_7d": lambda v: f"aparelho usado por {_plural(_n(v), 'outra conta', 'outras contas')} em 7 dias",
    "ip_distinct_accounts_24h": lambda v: f"IP usado por {_plural(_n(v), 'outra conta', 'outras contas')} em 24h",
    "km_from_usual_location": lambda v: f"{_n(v)} km da localização habitual",
    "geo_missing": lambda v: "Pix enviado sem geolocalização" if v else "Pix com geolocalização",
    "channel": lambda v: f"canal {v}",
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
FALLBACK_REASON = "combinação de sinais fora do padrão do pagador"
SAME_SIGNAL = {
    "dest_distinct_payers_7d": "dest_distinct_payers",
    "dest_distinct_payers_24h": "dest_distinct_payers",
    "payer_tx_count_1h": "payer_velocity",
    "payer_tx_count_24h": "payer_velocity",
    "payer_amount_sum_24h": "payer_velocity",
    "local_hour": "night",
    "is_night": "night",
}
MISSING_TEXT = {
    "payer_median_amount_90d": "pagador sem histórico de valores",
    "ratio_to_median": "sem valor típico do pagador para comparar",
    "km_from_usual_location": "sem localização habitual para comparar",
}


class FraudScorer:

    def __init__(self, models_dir):
        models_dir = Path(models_dir)
        self.preprocessor = joblib.load(models_dir / "preprocessor.joblib")
        self.model = joblib.load(models_dir / "fraud_model.joblib")
        with open(models_dir / "fraud_model_meta.json", encoding="utf-8") as f:
            self.meta = json.load(f)
        self.thresholds = self.meta["thresholds"]
        self.out_names = list(self.preprocessor.get_feature_names_out())

    def decide(self, score: float) -> str:
        if score >= self.thresholds["reject"]:
            return "rejected"
        if score >= self.thresholds["two_factor"]:
            return "two_factor_required"
        return "approved"

    def _base_feature(self, name: str):
        if name.startswith("missingindicator_"):
            return (name[len("missingindicator_") :], True)
        for cat in CAT_FEATURES:
            if name.startswith(cat + "_"):
                return (cat, False)
        return (name, False)

    def reasons(self, raw_row: pd.Series, contrib_row: np.ndarray, top: int = 3, min_contrib: float = 0.15) -> list:
        totals = {}
        for name, value in zip(self.out_names, contrib_row):
            base, _ = self._base_feature(name)
            totals[base] = totals.get(base, 0.0) + float(value)
        texts, used = ([], set())
        for feat, value in sorted(totals.items(), key=lambda kv: -kv[1]):
            if value < min_contrib or len(texts) >= top:
                break
            group = SAME_SIGNAL.get(feat, feat)
            if group in used:
                continue
            raw = raw_row[feat]
            if isinstance(raw, float) and math.isnan(raw):
                text = MISSING_TEXT.get(feat)
            elif feat in RISKY and RISKY[feat](raw):
                text = REASON_TEXT[feat](raw)
            else:
                text = None
            if text:
                texts.append(text)
                used.add(group)
        return texts or [FALLBACK_REASON]

    def score(self, features: pd.DataFrame) -> list:
        X = features[FEATURE_COLS]
        Xt = self.preprocessor.transform(X)
        scores = self.model.predict_proba(Xt)[:, 1]
        contribs = self.model.predict(Xt, pred_contrib=True)[:, :-1]
        results = []
        for i, s in enumerate(scores):
            status = self.decide(float(s))
            reasons = self.reasons(X.iloc[i], contribs[i]) if status != "approved" else []
            cold_start = (
                X.iloc[i]["payer_tx_count_90d"] == 0 and X.iloc[i]["source_account_age_days"] >= COLD_START_MIN_AGE_DAYS
            )
            if cold_start and status == "rejected":
                status = "two_factor_required"
                reasons = reasons + ["pagador ainda sem histórico no nosso banco: decisão limitada a 2FA"]
            results.append(
                {"status": status, "score": round(float(s), 4), "reasons": reasons, "cold_start": bool(cold_start)}
            )
        return results
